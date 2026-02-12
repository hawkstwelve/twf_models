import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";

import { BottomForecastControls } from "@/components/bottom-forecast-controls";
import { MapCanvas } from "@/components/map-canvas";
import { type LegendPayload, MapLegend } from "@/components/map-legend";
import { WeatherToolbar } from "@/components/weather-toolbar";
import {
  type LegacyFrameRow,
  type LegendMeta,
  type OfflineRunManifest,
  type VarRow,
  fetchLegacyFrames,
  fetchLegacyRegions,
  fetchLegacyRuns,
  fetchLegacyVars,
  fetchModels,
  fetchRunManifest,
  fetchRuns,
  fetchVars,
} from "@/lib/api";
import { DEFAULTS, FORCE_LEGACY_RUNTIME, VARIABLE_LABELS } from "@/lib/config";
import { buildRunOptions } from "@/lib/run-options";
import { buildLegacyTileUrlFromFrame, buildOfflinePmtilesUrl } from "@/lib/tiles";

const AUTOPLAY_TICK_MS = 500;
const MANIFEST_REFRESH_ACTIVE_MS = 5_000;
const MANIFEST_REFRESH_IDLE_MS = 30_000;
const LEGACY_REFRESH_MS = 30_000;
const RENDERER_MODE_STORAGE_KEY = "twf_renderer_mode";

type Option = {
  value: string;
  label: string;
};

type RendererMode = "offline" | "legacy";
type SourceKind = "pmtiles" | "xyz";
type NetworkRequestSource = "fetch" | "map";

type DisplayFrame = {
  frameId: string;
  fh: number;
  run: string;
  tileUrl: string;
  validTime?: string;
  legendMeta?: LegendMeta | null;
};

function pickPreferred(values: string[], preferred: string): string {
  if (values.includes(preferred)) {
    return preferred;
  }
  return values[0] ?? "";
}

function makeRegionLabel(id: string): string {
  return id.toUpperCase();
}

function makeVariableLabel(id: string, preferredLabel?: string | null): string {
  if (id === "precip_ptype") {
    return VARIABLE_LABELS.precip_ptype;
  }
  if (preferredLabel && preferredLabel.trim()) {
    return preferredLabel.trim();
  }
  return VARIABLE_LABELS[id] ?? id;
}

function normalizeVarRows(rows: VarRow[]): Array<{ id: string; displayName?: string }> {
  const normalized: Array<{ id: string; displayName?: string }> = [];
  for (const row of rows) {
    if (typeof row === "string") {
      const id = row.trim();
      if (!id) continue;
      normalized.push({ id });
      continue;
    }
    const id = String(row.id ?? "").trim();
    if (!id) continue;
    const displayName = row.display_name ?? row.name ?? row.label;
    normalized.push({ id, displayName: displayName?.trim() || undefined });
  }
  return normalized;
}

function extractLegacyLegendMeta(row: LegacyFrameRow | null | undefined): LegendMeta | null {
  const rawMeta = row?.meta?.meta ?? null;
  if (!rawMeta) return null;
  const nested = (rawMeta as { meta?: LegendMeta | null }).meta;
  return nested ?? (rawMeta as LegendMeta);
}

function nearestFrame(frames: number[], current: number): number {
  if (frames.length === 0) return 0;
  if (frames.includes(current)) return current;
  return frames.reduce((nearest, value) => {
    const nearestDelta = Math.abs(nearest - current);
    const valueDelta = Math.abs(value - current);
    return valueDelta < nearestDelta ? value : nearest;
  }, frames[0]);
}

function runIdToIso(runId: string | null): string | null {
  if (!runId) return null;
  const match = runId.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})z$/i);
  if (!match) return null;
  const [, year, month, day, hour] = match;
  return new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), 0, 0)).toISOString();
}

function isPrecipPtypeLegendMeta(
  meta: LegendMeta & { var_key?: string; spec_key?: string; id?: string }
): boolean {
  const kind = String(meta.kind ?? "").toLowerCase();
  const id = String(meta.var_key ?? meta.spec_key ?? meta.id ?? "").toLowerCase();
  return kind.includes("precip_ptype") || id === "precip_ptype";
}

function withPrecipRateUnits(title: string, units?: string): string {
  const resolvedUnits = (units ?? "").trim();
  if (!resolvedUnits) {
    return title;
  }
  const lowerTitle = title.toLowerCase();
  const lowerUnits = resolvedUnits.toLowerCase();
  if (lowerTitle.includes(`(${lowerUnits})`)) {
    return title;
  }
  return `${title} (${resolvedUnits})`;
}

function buildLegend(meta: LegendMeta | null | undefined, opacity: number): LegendPayload | null {
  if (!meta) {
    return null;
  }
  const metaWithIds = meta as LegendMeta & { var_key?: string; spec_key?: string; id?: string };
  const isPrecipPtype = isPrecipPtypeLegendMeta(metaWithIds);
  const baseTitle = meta.legend_title ?? meta.display_name ?? "Legend";
  const title = isPrecipPtype ? withPrecipRateUnits(baseTitle, meta.units) : baseTitle;
  const units = meta.units;
  const legendMetadata = {
    kind: metaWithIds.kind,
    id: metaWithIds.var_key ?? metaWithIds.spec_key ?? metaWithIds.id,
    ptype_breaks: metaWithIds.ptype_breaks,
    ptype_order: metaWithIds.ptype_order,
    bins_per_ptype: metaWithIds.bins_per_ptype,
  };

  if (Array.isArray(meta.legend_stops) && meta.legend_stops.length > 0) {
    const entries = meta.legend_stops
      .map(([value, color]) => ({ value: Number(value), color }))
      .filter((entry) => Number.isFinite(entry.value));
    if (entries.length === 0) {
      return null;
    }
    return {
      title,
      units,
      entries,
      opacity,
      ...legendMetadata,
    };
  }

  if (
    Array.isArray(meta.colors) &&
    meta.colors.length > 1 &&
    Array.isArray(meta.range) &&
    meta.range.length === 2
  ) {
    const [min, max] = meta.range;
    const entries = meta.colors.map((color, index) => {
      const denom = Math.max(1, meta.colors!.length - 1);
      const value = min + ((max - min) * index) / denom;
      return { value, color };
    });
    return {
      title,
      units,
      entries,
      opacity,
      ...legendMetadata,
    };
  }

  if (Array.isArray(meta.colors) && meta.colors.length > 0 && Array.isArray(meta.levels) && meta.levels.length > 0) {
    const maxItems = Math.min(meta.levels.length, meta.colors.length);
    const entries: Array<{ value: number; color: string }> = [];
    for (let index = 0; index < maxItems; index += 1) {
      const value = Number(meta.levels[index]);
      const color = meta.colors[index];
      if (!Number.isFinite(value) || !color) {
        continue;
      }
      entries.push({ value, color });
    }
    if (entries.length > 0) {
      return {
        title,
        units,
        entries,
        opacity,
        ...legendMetadata,
      };
    }
  }

  return null;
}

function readStoredRendererMode(): RendererMode | null {
  try {
    const value = window.localStorage.getItem(RENDERER_MODE_STORAGE_KEY);
    if (value === "legacy" || value === "offline") {
      return value;
    }
  } catch {
    // ignore storage access failures
  }
  return null;
}

function writeStoredRendererMode(value: RendererMode | null): void {
  try {
    if (value) {
      window.localStorage.setItem(RENDERER_MODE_STORAGE_KEY, value);
      return;
    }
    window.localStorage.removeItem(RENDERER_MODE_STORAGE_KEY);
  } catch {
    // ignore storage access failures
  }
}

function rendererModeQueryOverride(search: string): RendererMode | null {
  const params = new URLSearchParams(search);
  if (params.get("legacy") === "1") {
    return "legacy";
  }
  if (params.get("legacy") === "0" || params.get("offline") === "1") {
    return "offline";
  }
  return null;
}

function replaceRendererQuery(mode: RendererMode | null): void {
  const params = new URLSearchParams(window.location.search);
  params.delete("legacy");
  params.delete("offline");
  if (mode === "legacy") {
    params.set("legacy", "1");
  } else if (mode === "offline") {
    params.set("offline", "1");
  }
  const query = params.toString();
  const nextUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  window.history.replaceState(null, "", nextUrl);
}

function resolveRendererMode(): RendererMode {
  if (FORCE_LEGACY_RUNTIME) {
    return "legacy";
  }
  const queryOverride = rendererModeQueryOverride(window.location.search);
  if (queryOverride) {
    writeStoredRendererMode(queryOverride);
    return queryOverride;
  }
  return readStoredRendererMode() ?? "offline";
}

function isLegacyOverlayRequestUrl(inputUrl: string): boolean {
  try {
    const url = new URL(inputUrl, window.location.origin);
    const path = url.pathname.toLowerCase();
    if (path.includes("/api/v2/")) return true;
    if (path.includes("/tiles/v2/")) return true;
    if (path.includes("/tiles-titiler/")) return true;
    // Runtime legacy overlay shape: /tiles/{model}/{region}/{run}/{var}/{fh}/{z}/{x}/{y}.png
    if (/^\/tiles\/[^/]+\/[^/]+\/[^/]+\/[^/]+\/\d+\/\d+\/\d+\/\d+\.png$/.test(path)) {
      return true;
    }
  } catch {
    return false;
  }
  return false;
}

function getOfflineFrames(
  manifest: OfflineRunManifest,
  model: string,
  variable: string
): { frames: DisplayFrame[]; expected: number; available: number; runId: string } {
  const variableManifest = manifest.variables[variable];
  if (!variableManifest) {
    return { frames: [], expected: 0, available: 0, runId: manifest.run };
  }

  const frames = variableManifest.frames
    .slice()
    .sort((a, b) => Number(a.fhr) - Number(b.fhr))
    .map((frame) => ({
      frameId: frame.frame_id,
      fh: Number(frame.fhr),
      run: manifest.run,
      tileUrl: buildOfflinePmtilesUrl({
        model,
        run: manifest.run,
        varKey: variable,
        frameId: frame.frame_id,
        frameUrl: frame.url,
      }),
      validTime: frame.valid_time,
      legendMeta: null,
    }));

  return {
    frames,
    expected: variableManifest.expected_frames,
    available: variableManifest.available_frames,
    runId: manifest.run,
  };
}

export default function App() {
  const [rendererMode, setRendererMode] = useState<RendererMode>(() => resolveRendererMode());
  const sourceKind: SourceKind = rendererMode === "offline" ? "pmtiles" : "xyz";

  const [models, setModels] = useState<Option[]>([]);
  const [regions, setRegions] = useState<Option[]>([]);
  const [runs, setRuns] = useState<string[]>([]);
  const [variables, setVariables] = useState<Option[]>([]);
  const [frameRows, setFrameRows] = useState<DisplayFrame[]>([]);

  const [model, setModel] = useState(DEFAULTS.model);
  const [region, setRegion] = useState(DEFAULTS.region);
  const [run, setRun] = useState(DEFAULTS.run);
  const [variable, setVariable] = useState(DEFAULTS.variable);
  const [forecastHour, setForecastHour] = useState(0);
  const [targetForecastHour, setTargetForecastHour] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [opacity, setOpacity] = useState(DEFAULTS.overlayOpacity);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showZoomHint, setShowZoomHint] = useState(false);
  const [expectedFrames, setExpectedFrames] = useState(0);
  const [availableFramesCount, setAvailableFramesCount] = useState(0);
  const [resolvedRunId, setResolvedRunId] = useState<string | null>(null);
  const [legacyRequestViolations, setLegacyRequestViolations] = useState<string[]>([]);

  const frameHours = useMemo(() => {
    const hours = frameRows.map((row) => Number(row.fh)).filter(Number.isFinite);
    return Array.from(new Set(hours)).sort((a, b) => a - b);
  }, [frameRows]);

  const frameByHour = useMemo(() => {
    return new Map(frameRows.map((row) => [Number(row.fh), row]));
  }, [frameRows]);

  const currentFrame = frameByHour.get(forecastHour) ?? frameRows[0] ?? null;

  const latestRunId = useMemo(() => {
    if (rendererMode === "offline") {
      return resolvedRunId ?? runs[0] ?? null;
    }
    return frameRows[0]?.run ?? runs[0] ?? null;
  }, [rendererMode, resolvedRunId, runs, frameRows]);

  const resolvedRunForRequests = run === "latest" ? (latestRunId ?? "latest") : run;

  const runOptions = useMemo<Option[]>(() => {
    return buildRunOptions(runs, latestRunId);
  }, [runs, latestRunId]);

  const tileUrl = useMemo(() => {
    return currentFrame?.tileUrl ?? "";
  }, [currentFrame]);

  const legend = useMemo(() => {
    const normalizedMeta = currentFrame?.legendMeta ?? frameRows[0]?.legendMeta ?? null;
    return buildLegend(normalizedMeta, opacity);
  }, [currentFrame, frameRows, opacity]);

  const prefetchTileUrls = useMemo(() => {
    if (frameHours.length < 2) return [];
    const currentIndex = frameHours.indexOf(forecastHour);
    const start = currentIndex >= 0 ? currentIndex : 0;
    const prefetchCount = rendererMode === "offline" ? 2 : 4;
    const nextHours = Array.from({ length: prefetchCount }, (_, idx) => {
      const i = start + idx + 1;
      return i >= frameHours.length ? Number.NaN : frameHours[i];
    });
    const dedup = Array.from(new Set(nextHours.filter((fh) => Number.isFinite(fh) && fh !== forecastHour)));
    return dedup.map((fh) => frameByHour.get(fh)?.tileUrl).filter((url): url is string => Boolean(url));
  }, [frameHours, forecastHour, frameByHour, rendererMode]);

  const effectiveRunId = currentFrame?.run ?? (run !== "latest" ? run : latestRunId);
  const runDateTimeISO = runIdToIso(effectiveRunId);

  const isPublishing = rendererMode === "offline" && expectedFrames > 0 && availableFramesCount < expectedFrames;
  const refreshMs = rendererMode === "offline"
    ? isPublishing
      ? MANIFEST_REFRESH_ACTIVE_MS
      : MANIFEST_REFRESH_IDLE_MS
    : LEGACY_REFRESH_MS;

  const reportLegacyRequestViolation = useCallback(
    (url: string, source: NetworkRequestSource) => {
      if (rendererMode !== "offline") {
        return;
      }
      if (!isLegacyOverlayRequestUrl(url)) {
        return;
      }
      setLegacyRequestViolations((prev) => {
        if (prev.includes(url)) {
          return prev;
        }
        return [...prev.slice(-9), url];
      });
      console.error("[phase2] legacy overlay request detected in offline mode", { source, url });
    },
    [rendererMode]
  );

  useEffect(() => {
    if (FORCE_LEGACY_RUNTIME) {
      setRendererMode("legacy");
      return;
    }

    const syncFromLocation = () => {
      const queryOverride = rendererModeQueryOverride(window.location.search);
      if (queryOverride) {
        writeStoredRendererMode(queryOverride);
        setRendererMode(queryOverride);
        return;
      }
      setRendererMode(readStoredRendererMode() ?? "offline");
    };

    window.addEventListener("popstate", syncFromLocation);
    return () => window.removeEventListener("popstate", syncFromLocation);
  }, []);

  const setRendererPreference = (nextMode: RendererMode) => {
    if (FORCE_LEGACY_RUNTIME) {
      setRendererMode("legacy");
      return;
    }
    writeStoredRendererMode(nextMode);
    replaceRendererQuery(nextMode);
    setRendererMode(nextMode);
    setLegacyRequestViolations([]);
  };

  const resetRendererPreference = () => {
    if (FORCE_LEGACY_RUNTIME) {
      setRendererMode("legacy");
      return;
    }
    writeStoredRendererMode(null);
    replaceRendererQuery(null);
    setRendererMode("offline");
    setLegacyRequestViolations([]);
  };

  useEffect(() => {
    if (rendererMode !== "offline") {
      return;
    }

    const originalFetch = window.fetch.bind(window);
    const monitoredFetch: typeof window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      reportLegacyRequestViolation(requestUrl, "fetch");
      return originalFetch(input, init);
    };

    window.fetch = monitoredFetch;
    return () => {
      window.fetch = originalFetch;
    };
  }, [rendererMode, reportLegacyRequestViolation]);

  useEffect(() => {
    if (rendererMode !== "offline") {
      setLegacyRequestViolations([]);
    }
  }, [rendererMode]);

  useEffect(() => {
    let cancelled = false;

    async function loadModels() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchModels();
        if (cancelled) return;
        const options = data.map((item) => ({ value: item.id, label: item.name || item.id }));
        setModels(options);
        const modelIds = options.map((opt) => opt.value);
        const nextModel = pickPreferred(modelIds, DEFAULTS.model);
        setModel(nextModel);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load models");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadModels();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!model) return;
    let cancelled = false;

    async function loadRegions() {
      setError(null);
      if (rendererMode === "offline") {
        const offlineRegion = "published";
        setRegions([{ value: offlineRegion, label: makeRegionLabel(offlineRegion) }]);
        setRegion(offlineRegion);
        return;
      }

      try {
        const data = await fetchLegacyRegions(model);
        if (cancelled) return;
        const options = data.map((id) => ({ value: id, label: makeRegionLabel(id) }));
        setRegions(options);
        const regionIds = options.map((opt) => opt.value);
        const nextRegion = pickPreferred(regionIds, "pnw");
        setRegion((prev) => (regionIds.includes(prev) ? prev : nextRegion));
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load regions");
      }
    }

    loadRegions();
    return () => {
      cancelled = true;
    };
  }, [model, rendererMode]);

  useEffect(() => {
    if (!model || !region) return;
    let cancelled = false;

    async function loadRunsAndVars() {
      setError(null);
      try {
        const runData =
          rendererMode === "offline" ? await fetchRuns(model) : await fetchLegacyRuns(model, region);
        if (cancelled) return;

        const nextRun = run !== "latest" && runData.includes(run) ? run : "latest";
        const varData =
          rendererMode === "offline"
            ? await fetchVars(model, nextRun)
            : await fetchLegacyVars(model, region, nextRun);
        if (cancelled) return;

        setRuns(runData);

        const normalizedVars = normalizeVarRows(varData);
        const variableOptions = normalizedVars.map((entry) => ({
          value: entry.id,
          label: makeVariableLabel(entry.id, entry.displayName),
        }));
        setVariables(variableOptions);
        setRun(nextRun);

        const variableIds = variableOptions.map((opt) => opt.value);
        const nextVar = pickPreferred(variableIds, DEFAULTS.variable);
        setVariable((prev) => (variableIds.includes(prev) ? prev : nextVar));
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load runs/variables");
      }
    }

    loadRunsAndVars();
    return () => {
      cancelled = true;
    };
  }, [model, region, run, rendererMode]);

  useEffect(() => {
    setFrameRows([]);
    setForecastHour(0);
    setTargetForecastHour(0);
    setExpectedFrames(0);
    setAvailableFramesCount(0);
  }, [model, region, variable, rendererMode]);

  useEffect(() => {
    if (!model || !region || !variable) return;
    let cancelled = false;

    async function loadFrames() {
      setError(null);
      try {
        if (rendererMode === "offline") {
          const manifest = await fetchRunManifest(model, resolvedRunForRequests);
          if (cancelled) return;
          const payload = getOfflineFrames(manifest, model, variable);
          setResolvedRunId(payload.runId);
          setFrameRows(payload.frames);
          setAvailableFramesCount(payload.available);
          setExpectedFrames(payload.expected);
          const frames = payload.frames.map((row) => Number(row.fh)).filter(Number.isFinite);
          setForecastHour((prev) => nearestFrame(frames, prev));
          setTargetForecastHour((prev) => nearestFrame(frames, prev));
          return;
        }

        const rows = await fetchLegacyFrames(model, region, resolvedRunForRequests, variable);
        if (cancelled) return;
        const normalizedRows: DisplayFrame[] = rows.map((row) => {
          const runId = row.run ?? resolvedRunForRequests;
          return {
            frameId: String(row.fh).padStart(3, "0"),
            fh: Number(row.fh),
            run: runId,
            tileUrl: buildLegacyTileUrlFromFrame({
              model,
              region,
              run: runId,
              varKey: variable,
              fh: row.fh,
              frameRow: row,
            }),
            legendMeta: extractLegacyLegendMeta(row),
          };
        });
        setFrameRows(normalizedRows);
        setResolvedRunId(normalizedRows[0]?.run ?? null);
        setAvailableFramesCount(normalizedRows.length);
        setExpectedFrames(normalizedRows.length);
        const frames = normalizedRows.map((row) => Number(row.fh)).filter(Number.isFinite);
        setForecastHour((prev) => nearestFrame(frames, prev));
        setTargetForecastHour((prev) => nearestFrame(frames, prev));
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load frames");
        setFrameRows([]);
      }
    }

    loadFrames();
    return () => {
      cancelled = true;
    };
  }, [model, region, run, variable, resolvedRunForRequests, rendererMode]);

  useEffect(() => {
    if (!model || !region || !variable) {
      return;
    }
    const interval = window.setInterval(async () => {
      if (document.hidden) {
        return;
      }

      try {
        if (rendererMode === "offline") {
          const manifest = await fetchRunManifest(model, resolvedRunForRequests);
          const payload = getOfflineFrames(manifest, model, variable);
          setResolvedRunId(payload.runId);
          setFrameRows(payload.frames);
          setAvailableFramesCount(payload.available);
          setExpectedFrames(payload.expected);
          const frames = payload.frames.map((row) => Number(row.fh)).filter(Number.isFinite);
          setForecastHour((prev) => nearestFrame(frames, prev));
          setTargetForecastHour((prev) => nearestFrame(frames, prev));
          return;
        }

        const rows = await fetchLegacyFrames(model, region, resolvedRunForRequests, variable);
        const normalizedRows: DisplayFrame[] = rows.map((row) => {
          const runId = row.run ?? resolvedRunForRequests;
          return {
            frameId: String(row.fh).padStart(3, "0"),
            fh: Number(row.fh),
            run: runId,
            tileUrl: buildLegacyTileUrlFromFrame({
              model,
              region,
              run: runId,
              varKey: variable,
              fh: row.fh,
              frameRow: row,
            }),
            legendMeta: extractLegacyLegendMeta(row),
          };
        });
        setFrameRows(normalizedRows);
        setAvailableFramesCount(normalizedRows.length);
        setExpectedFrames(normalizedRows.length);
      } catch {
        // Background refresh should not interrupt active UI.
      }
    }, refreshMs);

    return () => window.clearInterval(interval);
  }, [model, region, run, variable, resolvedRunForRequests, refreshMs, rendererMode]);

  useEffect(() => {
    if (!isPlaying || frameHours.length === 0) return;

    const interval = window.setInterval(() => {
      const currentIndex = frameHours.indexOf(forecastHour);
      if (currentIndex < 0) return;

      const nextIndex = currentIndex + 1;
      if (nextIndex >= frameHours.length) {
        setIsPlaying(false);
        return;
      }
      setTargetForecastHour(frameHours[nextIndex]);
    }, AUTOPLAY_TICK_MS);

    return () => window.clearInterval(interval);
  }, [isPlaying, frameHours, forecastHour]);

  useEffect(() => {
    if (frameHours.length === 0 && isPlaying) {
      setIsPlaying(false);
    }
  }, [frameHours, isPlaying]);

  useEffect(() => {
    if (frameHours.length === 0) {
      return;
    }
    const nextTarget = nearestFrame(frameHours, targetForecastHour);
    if (nextTarget === forecastHour) {
      return;
    }
    setForecastHour(nextTarget);
  }, [targetForecastHour, forecastHour, frameHours]);

  return (
    <div className="flex h-full flex-col">
      <WeatherToolbar
        region={region}
        onRegionChange={setRegion}
        model={model}
        onModelChange={setModel}
        run={run}
        onRunChange={setRun}
        variable={variable}
        onVariableChange={setVariable}
        regions={regions}
        models={models}
        runs={runOptions}
        variables={variables}
        showRegion={rendererMode === "legacy"}
        disabled={loading || models.length === 0}
      />

      <div className="relative flex-1 overflow-hidden">
        <MapCanvas
          tileUrl={tileUrl}
          sourceKind={sourceKind}
          region={region}
          opacity={opacity}
          mode={isPlaying ? "autoplay" : "scrub"}
          variable={variable}
          model={model}
          prefetchTileUrls={prefetchTileUrls}
          crossfade={false}
          onZoomHint={setShowZoomHint}
          onRequestUrl={(url) => reportLegacyRequestViolation(url, "map")}
        />

        <div className="absolute right-4 top-4 z-40 rounded-md border border-border/50 bg-[hsl(var(--toolbar))]/95 px-3 py-2 text-xs shadow-xl backdrop-blur-md">
          <div className="font-medium">Renderer mode</div>
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              className="rounded border border-border/60 px-2 py-1 text-[11px] disabled:opacity-50"
              onClick={() => setRendererPreference("offline")}
              disabled={rendererMode === "offline"}
            >
              Offline
            </button>
            <button
              type="button"
              className="rounded border border-border/60 px-2 py-1 text-[11px] disabled:opacity-50"
              onClick={() => setRendererPreference("legacy")}
              disabled={rendererMode === "legacy" || FORCE_LEGACY_RUNTIME}
            >
              Legacy
            </button>
            <button
              type="button"
              className="rounded border border-border/60 px-2 py-1 text-[11px]"
              onClick={resetRendererPreference}
              disabled={FORCE_LEGACY_RUNTIME}
            >
              Reset
            </button>
          </div>
        </div>

        {rendererMode === "legacy" && (
          <div className="absolute left-4 top-4 z-40 rounded-md border border-amber-500/40 bg-amber-500/15 px-3 py-2 text-xs shadow-lg backdrop-blur-md">
            Legacy fallback mode enabled via <code>?legacy=1</code>
          </div>
        )}

        {error && (
          <div className="absolute left-4 top-16 z-40 flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive shadow-lg backdrop-blur-md">
            <AlertCircle className="h-3.5 w-3.5" />
            {error}
          </div>
        )}

        {rendererMode === "offline" && legacyRequestViolations.length > 0 && (
          <div className="absolute left-4 top-28 z-40 rounded-md border border-red-500/50 bg-red-500/10 px-3 py-2 text-xs text-red-200 shadow-lg backdrop-blur-md">
            Legacy network check failed ({legacyRequestViolations.length}) - latest:
            {" "}
            <code>{legacyRequestViolations[legacyRequestViolations.length - 1]}</code>
          </div>
        )}

        {showZoomHint && (
          <div className="absolute left-1/2 top-4 z-40 flex -translate-x-1/2 items-center gap-2 rounded-md border border-border/50 bg-[hsl(var(--toolbar))]/95 px-3 py-2 text-xs shadow-xl backdrop-blur-md">
            <AlertCircle className="h-3.5 w-3.5" />
            GFS is low-resolution at this zoom. Switch to HRRR for sharper detail.
          </div>
        )}

        <MapLegend legend={legend} onOpacityChange={setOpacity} />

        <BottomForecastControls
          forecastHour={forecastHour}
          availableFrames={frameHours}
          availableFramesCount={availableFramesCount}
          expectedFramesCount={expectedFrames}
          isPublishing={isPublishing}
          rendererMode={rendererMode}
          onForecastHourChange={setTargetForecastHour}
          isPlaying={isPlaying}
          setIsPlaying={setIsPlaying}
          runDateTimeISO={runDateTimeISO}
          disabled={loading}
        />
      </div>
    </div>
  );
}
