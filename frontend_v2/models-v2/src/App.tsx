import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";

import { BottomForecastControls } from "@/components/bottom-forecast-controls";
import { MapCanvas } from "@/components/map-canvas";
import { type LegendPayload, MapLegend } from "@/components/map-legend";
import { WeatherToolbar } from "@/components/weather-toolbar";
import {
  type LegendMeta,
  type OfflineRunManifest,
  type VarRow,
  fetchModels,
  fetchRunManifest,
  fetchRuns,
  fetchVars,
} from "@/lib/api";
import { DEFAULTS, VARIABLE_LABELS } from "@/lib/config";
import { buildRunOptions } from "@/lib/run-options";
import { buildOfflinePmtilesUrl } from "@/lib/tiles";

const AUTOPLAY_TICK_MS = 500;
const MANIFEST_REFRESH_ACTIVE_MS = 5_000;
const MANIFEST_REFRESH_IDLE_MS = 30_000;

type Option = {
  value: string;
  label: string;
};

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

function isLegacyRequestUrl(inputUrl: string): boolean {
  try {
    const url = new URL(inputUrl, window.location.origin);
    const path = url.pathname.toLowerCase();
    return path.includes("/api/v2/") || path.includes("/tiles/v2/");
  } catch {
    return false;
  }
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
  const [models, setModels] = useState<Option[]>([]);
  const [regions] = useState<Option[]>([{ value: "published", label: makeRegionLabel("published") }]);
  const [runs, setRuns] = useState<string[]>([]);
  const [variables, setVariables] = useState<Option[]>([]);
  const [frameRows, setFrameRows] = useState<DisplayFrame[]>([]);

  const [model, setModel] = useState(DEFAULTS.model);
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
    return resolvedRunId ?? runs[0] ?? null;
  }, [resolvedRunId, runs]);

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
    const prefetchCount = 2;
    const nextHours = Array.from({ length: prefetchCount }, (_, idx) => {
      const i = start + idx + 1;
      return i >= frameHours.length ? Number.NaN : frameHours[i];
    });
    const dedup = Array.from(new Set(nextHours.filter((fh) => Number.isFinite(fh) && fh !== forecastHour)));
    return dedup.map((fh) => frameByHour.get(fh)?.tileUrl).filter((url): url is string => Boolean(url));
  }, [frameHours, forecastHour, frameByHour]);

  const effectiveRunId = currentFrame?.run ?? (run !== "latest" ? run : latestRunId);
  const runDateTimeISO = runIdToIso(effectiveRunId);

  const isPublishing = expectedFrames > 0 && availableFramesCount < expectedFrames;
  const refreshMs = isPublishing ? MANIFEST_REFRESH_ACTIVE_MS : MANIFEST_REFRESH_IDLE_MS;

  const reportLegacyRequestViolation = useCallback((url: string, source: NetworkRequestSource) => {
    if (!import.meta.env.DEV) {
      return;
    }
    if (!isLegacyRequestUrl(url)) {
      return;
    }
    setLegacyRequestViolations((prev) => {
      if (prev.includes(url)) {
        return prev;
      }
      return [...prev.slice(-9), url];
    });
    console.warn("[phase2] Legacy API/tile request detected", { source, url });
  }, []);

  useEffect(() => {
    if (!import.meta.env.DEV) {
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
  }, [reportLegacyRequestViolation]);

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

    async function loadRunsAndVars() {
      setError(null);
      try {
        const runData = await fetchRuns(model);
        if (cancelled) return;

        const nextRun = run !== "latest" && runData.includes(run) ? run : "latest";
        const varData = await fetchVars(model, nextRun);
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
  }, [model, run]);

  useEffect(() => {
    setFrameRows([]);
    setForecastHour(0);
    setTargetForecastHour(0);
    setExpectedFrames(0);
    setAvailableFramesCount(0);
  }, [model, run, variable]);

  useEffect(() => {
    if (!model || !variable) return;
    let cancelled = false;

    async function loadFrames() {
      setError(null);
      try {
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
  }, [model, run, variable, resolvedRunForRequests]);

  useEffect(() => {
    if (!model || !variable) {
      return;
    }
    const interval = window.setInterval(async () => {
      if (document.hidden) {
        return;
      }

      try {
        const manifest = await fetchRunManifest(model, resolvedRunForRequests);
        const payload = getOfflineFrames(manifest, model, variable);
        setResolvedRunId(payload.runId);
        setFrameRows(payload.frames);
        setAvailableFramesCount(payload.available);
        setExpectedFrames(payload.expected);
        const frames = payload.frames.map((row) => Number(row.fh)).filter(Number.isFinite);
        setForecastHour((prev) => nearestFrame(frames, prev));
        setTargetForecastHour((prev) => nearestFrame(frames, prev));
      } catch {
        // Background refresh should not interrupt active UI.
      }
    }, refreshMs);

    return () => window.clearInterval(interval);
  }, [model, run, variable, resolvedRunForRequests, refreshMs]);

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
        region="published"
        onRegionChange={() => {
          // Region is fixed to published-only discovery in offline mode.
        }}
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
        showRegion={false}
        disabled={loading || models.length === 0}
      />

      <div className="relative flex-1 overflow-hidden">
        <MapCanvas
          tileUrl={tileUrl}
          region="published"
          opacity={opacity}
          mode={isPlaying ? "autoplay" : "scrub"}
          variable={variable}
          model={model}
          prefetchTileUrls={prefetchTileUrls}
          crossfade={false}
          onZoomHint={setShowZoomHint}
          onRequestUrl={(url) => reportLegacyRequestViolation(url, "map")}
        />

        {error && (
          <div className="absolute left-4 top-4 z-40 flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive shadow-lg backdrop-blur-md">
            <AlertCircle className="h-3.5 w-3.5" />
            {error}
          </div>
        )}

        {!loading && !error && frameHours.length === 0 && (
          <div className="absolute left-4 top-16 z-40 rounded-md border border-amber-500/40 bg-amber-500/15 px-3 py-2 text-xs shadow-lg backdrop-blur-md">
            No frames published yet for this model/run/variable.
            {expectedFrames > 0 ? ` Still publishing (0/${expectedFrames}).` : ""}
          </div>
        )}

        {import.meta.env.DEV && legacyRequestViolations.length > 0 && (
          <div className="absolute left-4 top-28 z-40 rounded-md border border-red-500/50 bg-red-500/10 px-3 py-2 text-xs text-red-200 shadow-lg backdrop-blur-md">
            Dev guard: legacy request detected ({legacyRequestViolations.length}) - latest:
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
