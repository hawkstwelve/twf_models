import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { buildOfflineFrameImageUrl } from "@/lib/frames";
import { buildRunOptions } from "@/lib/run-options";

const MANIFEST_REFRESH_ACTIVE_MS = 5_000;
const MANIFEST_REFRESH_IDLE_MS = 30_000;
const SCRUB_RENDER_THROTTLE_MS = 80;
const PREFETCH_LOOKAHEAD = 20;

const TMP2M_COLORS = [
  "#e8d0d8", "#d8b0c8", "#c080b0", "#9050a0", "#703090",
  "#a070b0", "#c8a0d0", "#e8e0f0", "#d0e0f0", "#a0c0e0",
  "#7090c0", "#4070b0", "#2050a0", "#103070", "#204048",
  "#406058", "#709078", "#a0c098", "#d0e0b0", "#f0f0c0",
  "#e0d0a0", "#c0b080", "#a08060", "#805040", "#602018",
  "#801010", "#a01010", "#702020", "#886666", "#a08888",
  "#c0a0a0", "#d8c8c8", "#e8e0e0", "#b0a0a0", "#807070", "#504040",
] as const;

const PRECIP_COLORS = [
  "#c0c0c0", "#909090", "#606060", "#b0f090", "#80e060", "#50c040",
  "#3070f0", "#5090f0", "#80b0f0", "#b0d0f0", "#ffff80", "#ffd060",
  "#ffa040", "#ff6030", "#e03020", "#a01010", "#700000", "#d0b0e0",
  "#b080d0", "#9050c0", "#7020a0", "#c040c0",
] as const;

const PRECIP_LEVELS = [
  0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.2, 1.6, 2.0,
  3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 25.0,
] as const;

const WSPD10M_LEGEND_STOPS: [number, string][] = [
  [0, "#FFFFFF"], [4, "#E6F2FF"], [6, "#CCE5FF"], [8, "#99CCFF"], [9, "#66B2FF"], [10, "#3399FF"],
  [12, "#66FF66"], [14, "#33FF33"], [16, "#00FF00"], [20, "#CCFF33"], [22, "#FFFF00"], [24, "#FFCC00"],
  [26, "#FF9900"], [30, "#FF6600"], [34, "#FF3300"], [36, "#FF0000"], [40, "#CC0000"], [44, "#990000"],
  [48, "#800000"], [52, "#660033"], [58, "#660066"], [64, "#800080"], [70, "#990099"], [75, "#B300B3"],
  [85, "#CC00CC"], [95, "#E600E6"], [100, "#680868"],
];

const RAIN_LEVELS = [0.01, 0.1, 0.25, 0.5, 1.0, 1.5, 2.5, 4, 6, 10, 16, 24] as const;
const SNOW_LEVELS = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0] as const;
const WINTER_LEVELS = [0.1, 0.5, 1, 2, 3, 4, 6, 10, 14] as const;

const RAIN_PTYPE_COLORS = [
  "#90ee90", "#66dd66", "#33cc33", "#00bb00", "#009900", "#007700",
  "#005500", "#ffff00", "#ffb300", "#ff6600", "#ff0000", "#ff00ff",
] as const;
const FRZR_PTYPE_COLORS = [
  "#ffc0cb", "#ff69b4", "#ff1493", "#c71585", "#931040", "#b03060",
  "#d20000", "#ff2400", "#ff4500",
] as const;
const SLEET_PTYPE_COLORS = [
  "#e0ffff", "#add8e6", "#9370db", "#8a2be2", "#9400d3", "#800080",
  "#4b0082", "#8b008b", "#b22222",
] as const;
const SNOW_PTYPE_COLORS = [
  "#c0ffff", "#55ffff", "#4feaff", "#48d3ff", "#42bfff", "#3caaff",
  "#3693ff", "#2a69f1", "#1d42ca", "#1b18dc", "#161fb8", "#130495",
  "#130495", "#550a87", "#550a87", "#af068e", "#ea0081",
] as const;

const RADAR_RAIN_COLORS = [
  "#ffffff", "#4efb4c", "#46e444", "#3ecd3d", "#36b536", "#2d9e2e", "#258528",
  "#1d6e1f", "#155719", "#feff50", "#fad248", "#f8a442", "#f6763c", "#f5253a",
  "#de0a35", "#c21230", "#9c0045", "#bc0f9c", "#e300c1", "#f600dc",
] as const;
const RADAR_SNOW_COLORS = [
  "#ffffff", "#55ffff", "#4feaff", "#48d3ff", "#42bfff", "#3caaff", "#3693ff",
  "#2a6aee", "#1e40d0", "#110ba7", "#2a009a", "#0c276f", "#540093", "#bc0f9c",
  "#d30085", "#f5007f",
] as const;
const RADAR_SLEET_COLORS = [
  "#ffffff", "#b49dff", "#b788ff", "#c56cff", "#c54ef9", "#c54ef9", "#b730e7",
  "#a913d3", "#a913d3", "#9b02b4", "#bc0f9c", "#a50085", "#c52c7b", "#cf346f",
  "#d83c64", "#e24556",
] as const;
const RADAR_FRZR_COLORS = [
  "#ffffff", "#fbcad0", "#f893ba", "#e96c9f", "#dd88a5", "#dc4f8b", "#d03a80",
  "#c62773", "#bd1366", "#b00145", "#c21230", "#da2d0d", "#e33403", "#f53c00",
  "#f53c00", "#f54603",
] as const;

const FRONTEND_LEGEND_PRESETS: Record<string, LegendMeta> = {
  tmp2m: {
    kind: "tmp2m",
    display_name: "2m Temperature",
    legend_title: "Temperature (°F)",
    units: "F",
    range: [-40.0, 122.5],
    colors: [...TMP2M_COLORS],
  },
  wspd10m: {
    kind: "wspd10m",
    display_name: "10m Wind Speed",
    legend_title: "Wind Speed (mph)",
    units: "mph",
    range: [0.0, 100.0],
    legend_stops: WSPD10M_LEGEND_STOPS,
  },
  qpf6h: {
    kind: "qpf6h",
    display_name: "6-hr Precip",
    legend_title: "6-hr Precip (in)",
    units: "in",
    range: [0.0, 6.0],
    legend_stops: PRECIP_LEVELS.map((level, idx) => [level, PRECIP_COLORS[idx]]),
  },
  precip_ptype: {
    kind: "precip_ptype",
    display_name: "Precipitation Intensity",
    legend_title: "Precipitation Rate (mm/hr)",
    units: "mm/hr",
    ptype_order: ["frzr", "sleet", "snow", "rain"],
    ptype_breaks: {
      frzr: { offset: 0, count: FRZR_PTYPE_COLORS.length },
      sleet: { offset: FRZR_PTYPE_COLORS.length, count: SLEET_PTYPE_COLORS.length },
      snow: {
        offset: FRZR_PTYPE_COLORS.length + SLEET_PTYPE_COLORS.length,
        count: SNOW_PTYPE_COLORS.length,
      },
      rain: {
        offset: FRZR_PTYPE_COLORS.length + SLEET_PTYPE_COLORS.length + SNOW_PTYPE_COLORS.length,
        count: RAIN_PTYPE_COLORS.length,
      },
    },
    bins_per_ptype: 16,
    legend_stops: [
      ...FRZR_PTYPE_COLORS.map((color, idx) => [WINTER_LEVELS[idx], color] as [number, string]),
      ...SLEET_PTYPE_COLORS.map((color, idx) => [WINTER_LEVELS[idx], color] as [number, string]),
      ...SNOW_PTYPE_COLORS.map((color, idx) => [SNOW_LEVELS[idx], color] as [number, string]),
      ...RAIN_PTYPE_COLORS.map((color, idx) => [RAIN_LEVELS[idx], color] as [number, string]),
    ],
  },
  radar_ptype: {
    kind: "radar_ptype",
    display_name: "Composite Reflectivity + P-Type",
    legend_title: "Composite Reflectivity + P-Type (dBZ)",
    units: "dBZ",
    ptype_order: ["rain", "snow", "sleet", "frzr"],
    ptype_breaks: {
      rain: { offset: 0, count: RADAR_RAIN_COLORS.length },
      snow: { offset: RADAR_RAIN_COLORS.length, count: RADAR_SNOW_COLORS.length },
      sleet: { offset: RADAR_RAIN_COLORS.length + RADAR_SNOW_COLORS.length, count: RADAR_SLEET_COLORS.length },
      frzr: {
        offset: RADAR_RAIN_COLORS.length + RADAR_SNOW_COLORS.length + RADAR_SLEET_COLORS.length,
        count: RADAR_FRZR_COLORS.length,
      },
    },
    legend_stops: [
      ...RADAR_RAIN_COLORS.map((color, idx) => [idx + 1, color] as [number, string]),
      ...RADAR_SNOW_COLORS.map((color, idx) => [idx + 1, color] as [number, string]),
      ...RADAR_SLEET_COLORS.map((color, idx) => [idx + 1, color] as [number, string]),
      ...RADAR_FRZR_COLORS.map((color, idx) => [idx + 1, color] as [number, string]),
    ],
  },
};

type Option = {
  value: string;
  label: string;
};

type AutoplaySpeedPreset = {
  label: string;
  tickMs: number;
};

const AUTOPLAY_SPEED_PRESETS: AutoplaySpeedPreset[] = [
  { label: "0.5x", tickMs: 1000 },
  { label: "1x", tickMs: 500 },
  { label: "2x", tickMs: 250 },
];

type NetworkRequestSource = "fetch" | "map";

type DisplayFrame = {
  frameId: string;
  fh: number;
  run: string;
  frameImageUrl?: string;
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

  const manifestFrames = Array.isArray(variableManifest.frames) ? variableManifest.frames : [];
  const frames = manifestFrames
    .slice()
    .sort((a, b) => Number(a.fhr) - Number(b.fhr))
    .map((frame) => {
      const rawFrameImageUrl = frame.frame_image_url?.trim();
      return {
        frameId: frame.frame_id,
        fh: Number(frame.fhr),
        run: manifest.run,
        frameImageUrl: rawFrameImageUrl
          ? buildOfflineFrameImageUrl({
              model,
              run: manifest.run,
              varKey: variable,
              fh: frame.fhr,
              frameImageUrl: rawFrameImageUrl,
            })
          : undefined,
        validTime: frame.valid_time,
        legendMeta: FRONTEND_LEGEND_PRESETS[variable] ?? null,
      };
    });

  const expected = Number(variableManifest.expected_frames);
  const available = Number(variableManifest.available_frames);
  return {
    frames,
    expected: Number.isFinite(expected) ? expected : manifestFrames.length,
    available: Number.isFinite(available) ? available : frames.length,
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
  const [autoplayTickMs, setAutoplayTickMs] = useState(
    AUTOPLAY_SPEED_PRESETS.find((preset) => preset.label === "1x")?.tickMs ?? 500
  );
  const [opacity, setOpacity] = useState(DEFAULTS.overlayOpacity);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showZoomHint, setShowZoomHint] = useState(false);
  const [expectedFrames, setExpectedFrames] = useState(0);
  const [availableFramesCount, setAvailableFramesCount] = useState(0);
  const [resolvedRunId, setResolvedRunId] = useState<string | null>(null);
  const [legacyRequestViolations, setLegacyRequestViolations] = useState<string[]>([]);
  const [readyVersionImages, setReadyVersionImages] = useState(0);
  const [badFrameImageVersion, setBadFrameImageVersion] = useState(0);
  const [scrubIsActive, setScrubIsActive] = useState(false);
  const readyFrameImageUrlsRef = useRef<Set<string>>(new Set());
  const badFrameImageUrlsRef = useRef<Set<string>>(new Set());
  const scrubRenderTimerRef = useRef<number | null>(null);
  const lastScrubRenderAtRef = useRef(0);

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

  const frameImageUrl = useMemo(() => {
    const normalized = currentFrame?.frameImageUrl?.trim() ?? "";
    if (!normalized) {
      return "";
    }
    if (badFrameImageUrlsRef.current.has(normalized)) {
      return "";
    }
    return normalized;
  }, [currentFrame, badFrameImageVersion]);

  const legend = useMemo(() => {
    const normalizedMeta =
      currentFrame?.legendMeta ?? frameRows[0]?.legendMeta ?? FRONTEND_LEGEND_PRESETS[variable] ?? null;
    return buildLegend(normalizedMeta, opacity);
  }, [currentFrame, frameRows, opacity, variable]);

  const prefetchFrameImageUrls = useMemo<string[]>(() => {
    if (frameHours.length < 2) return [];
    const focusHour = nearestFrame(frameHours, isPlaying ? forecastHour : targetForecastHour);
    const focusIndex = frameHours.indexOf(focusHour);
    if (focusIndex < 0) return [];

    const prioritizedHours: number[] = [focusHour];
    for (let offset = 1; offset <= PREFETCH_LOOKAHEAD; offset += 1) {
      const ahead = focusIndex + offset;
      const behind = focusIndex - offset;
      if (ahead < frameHours.length) prioritizedHours.push(frameHours[ahead]);
      if (behind >= 0) prioritizedHours.push(frameHours[behind]);
    }

    return prioritizedHours.reduce<string[]>((items, fh) => {
      const frame = frameByHour.get(fh);
      const imageUrl = frame?.frameImageUrl?.trim();
      if (!imageUrl) return items;
      if (badFrameImageUrlsRef.current.has(imageUrl)) return items;
      if (items.includes(imageUrl)) return items;
      items.push(imageUrl);
      return items;
    }, []);
  }, [frameHours, frameByHour, forecastHour, targetForecastHour, isPlaying, badFrameImageVersion]);

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

  const markFrameImageReady = useCallback((imageUrl: string) => {
    const normalized = imageUrl.trim();
    if (!normalized) return;
    let changedImages = false;
    if (!readyFrameImageUrlsRef.current.has(normalized)) {
      readyFrameImageUrlsRef.current.add(normalized);
      changedImages = true;
    }
    if (badFrameImageUrlsRef.current.delete(normalized)) {
      setBadFrameImageVersion((prev) => prev + 1);
    }
    if (changedImages) {
      setReadyVersionImages((prev) => prev + 1);
    }
  }, []);

  const markFrameImageUnavailable = useCallback((imageUrl: string) => {
    const normalized = imageUrl.trim();
    if (!normalized) return;
    if (badFrameImageUrlsRef.current.has(normalized)) {
      return;
    }
    badFrameImageUrlsRef.current.add(normalized);
    setBadFrameImageVersion((prev) => prev + 1);
  }, []);

  const nearestReadyImageHour = useCallback(
    (targetHour: number, currentHour: number): number => {
      let winner: number | null = null;
      let winnerDistance = Number.POSITIVE_INFINITY;
      for (const hour of frameHours) {
        const imageUrl = frameByHour.get(hour)?.frameImageUrl?.trim();
        if (!imageUrl || badFrameImageUrlsRef.current.has(imageUrl) || !readyFrameImageUrlsRef.current.has(imageUrl)) {
          continue;
        }
        const distance = Math.abs(hour - targetHour);
        if (distance < winnerDistance) {
          winner = hour;
          winnerDistance = distance;
        }
      }
      return winner ?? currentHour;
    },
    [frameHours, frameByHour]
  );

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
    setScrubIsActive(false);
    readyFrameImageUrlsRef.current = new Set();
    badFrameImageUrlsRef.current = new Set();
    setReadyVersionImages((prev) => prev + 1);
    setBadFrameImageVersion((prev) => prev + 1);
  }, [model, run, variable]);

  useEffect(() => {
    const allowedImages = new Set(
      frameRows
        .map((row) => row.frameImageUrl?.trim())
        .filter((url): url is string => Boolean(url))
    );
    const nextReadyImages = new Set<string>();
    for (const imageUrl of readyFrameImageUrlsRef.current) {
      if (allowedImages.has(imageUrl)) {
        nextReadyImages.add(imageUrl);
      }
    }
    let changedImages = nextReadyImages.size !== readyFrameImageUrlsRef.current.size;
    if (!changedImages) {
      for (const imageUrl of nextReadyImages) {
        if (!readyFrameImageUrlsRef.current.has(imageUrl)) {
          changedImages = true;
          break;
        }
      }
    }
    readyFrameImageUrlsRef.current = nextReadyImages;
    if (changedImages) {
      setReadyVersionImages((prev) => prev + 1);
    }

    const nextBadImages = new Set<string>();
    for (const imageUrl of badFrameImageUrlsRef.current) {
      if (allowedImages.has(imageUrl)) {
        nextBadImages.add(imageUrl);
      }
    }
    let changedBadImages = nextBadImages.size !== badFrameImageUrlsRef.current.size;
    if (!changedBadImages) {
      for (const imageUrl of nextBadImages) {
        if (!badFrameImageUrlsRef.current.has(imageUrl)) {
          changedBadImages = true;
          break;
        }
      }
    }
    badFrameImageUrlsRef.current = nextBadImages;
    if (changedBadImages) {
      setBadFrameImageVersion((prev) => prev + 1);
    }
  }, [frameRows]);

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
    if (!isPlaying || frameHours.length === 0) {
      return;
    }

    const startHour = nearestFrame(frameHours, forecastHour);
    const startIndex = Math.max(0, frameHours.indexOf(startHour));
    const frameDurationMs = Math.max(1, autoplayTickMs);
    const startedAt = performance.now();
    let rafId: number | null = null;
    let lastIndex = -1;

    const tick = (now: number) => {
      const elapsed = now - startedAt;
      const advancedFrames = Math.floor(elapsed / frameDurationMs);
      const nextIndex = Math.min(frameHours.length - 1, startIndex + advancedFrames);
      if (nextIndex !== lastIndex) {
        lastIndex = nextIndex;
        const nextHour = frameHours[nextIndex];
        setForecastHour((prev) => (prev === nextHour ? prev : nextHour));
        setTargetForecastHour((prev) => (prev === nextHour ? prev : nextHour));
      }

      if (nextIndex >= frameHours.length - 1) {
        setIsPlaying(false);
        return;
      }

      rafId = window.requestAnimationFrame(tick);
    };

    rafId = window.requestAnimationFrame(tick);
    return () => {
      if (rafId !== null) {
        window.cancelAnimationFrame(rafId);
      }
    };
  }, [isPlaying, frameHours, autoplayTickMs]);

  useEffect(() => {
    if (frameHours.length === 0 && isPlaying) {
      setIsPlaying(false);
    }
  }, [frameHours, isPlaying]);

  useEffect(() => {
    if (isPlaying && scrubIsActive) {
      setScrubIsActive(false);
    }
  }, [isPlaying, scrubIsActive]);

  useEffect(() => {
    if (isPlaying || frameHours.length === 0) {
      return;
    }

    const target = nearestFrame(frameHours, targetForecastHour);
    const desiredHour = scrubIsActive ? nearestReadyImageHour(target, forecastHour) : target;
    const now = performance.now();
    const elapsed = now - lastScrubRenderAtRef.current;

    const apply = () => {
      lastScrubRenderAtRef.current = performance.now();
      setForecastHour((prev) => (prev === desiredHour ? prev : desiredHour));
    };

    if (elapsed >= SCRUB_RENDER_THROTTLE_MS) {
      apply();
      return;
    }

    const delay = Math.max(0, SCRUB_RENDER_THROTTLE_MS - elapsed);
    scrubRenderTimerRef.current = window.setTimeout(() => {
      scrubRenderTimerRef.current = null;
      apply();
    }, delay);

    return () => {
      if (scrubRenderTimerRef.current !== null) {
        window.clearTimeout(scrubRenderTimerRef.current);
        scrubRenderTimerRef.current = null;
      }
    };
  }, [isPlaying, frameHours, targetForecastHour, forecastHour, scrubIsActive, readyVersionImages, nearestReadyImageHour]);

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
          frameImageUrl={frameImageUrl}
          region="published"
          opacity={opacity}
          mode={isPlaying ? "autoplay" : "scrub"}
          variable={variable}
          model={model}
          scrubIsActive={scrubIsActive}
          prefetchFrameImageUrls={prefetchFrameImageUrls}
          crossfade={false}
          onFrameImageReady={markFrameImageReady}
          onFrameImageError={markFrameImageUnavailable}
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
          onScrubStart={() => setScrubIsActive(true)}
          onScrubEnd={() => setScrubIsActive(false)}
          isPlaying={isPlaying}
          setIsPlaying={setIsPlaying}
          autoplayTickMs={autoplayTickMs}
          autoplaySpeedPresets={AUTOPLAY_SPEED_PRESETS}
          onAutoplayTickMsChange={setAutoplayTickMs}
          runDateTimeISO={runDateTimeISO}
          disabled={loading}
        />
      </div>
    </div>
  );
}
