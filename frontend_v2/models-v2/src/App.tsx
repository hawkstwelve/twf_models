import { useEffect, useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";

import { BottomForecastControls } from "@/components/bottom-forecast-controls";
import { MapCanvas } from "@/components/map-canvas";
import { type LegendPayload, MapLegend } from "@/components/map-legend";
import { WeatherToolbar } from "@/components/weather-toolbar";
import {
  type FrameRow,
  type LegendMeta,
  fetchFrames,
  fetchModels,
  fetchRegions,
  fetchRuns,
  fetchVars,
} from "@/lib/api";
import { ALLOWED_VARIABLES, DEFAULTS, VARIABLE_LABELS } from "@/lib/config";
import { buildTileUrlFromFrame } from "@/lib/tiles";

type Option = {
  value: string;
  label: string;
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

function makeVariableLabel(id: string): string {
  return VARIABLE_LABELS[id] ?? id;
}

function latestRunLabel(runId: string | null): string {
  if (!runId) {
    return "Latest";
  }
  const match = runId.match(/_(\d{2})z$/i);
  return match ? `Latest (${match[1]}z)` : "Latest";
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

function buildLegend(meta: LegendMeta | null | undefined, opacity: number): LegendPayload | null {
  if (!meta) {
    return null;
  }

  if (Array.isArray(meta.legend_stops) && meta.legend_stops.length > 0) {
    const entries = meta.legend_stops
      .map(([value, color]) => ({ value: Number(value), color }))
      .filter((entry) => Number.isFinite(entry.value));
    if (entries.length === 0) {
      return null;
    }
    return {
      title: meta.legend_title ?? "Legend",
      units: meta.units,
      entries,
      opacity,
    };
  }

  if (Array.isArray(meta.colors) && meta.colors.length > 1 && Array.isArray(meta.range) && meta.range.length === 2) {
    const [min, max] = meta.range;
    const entries = meta.colors.map((color, index) => {
      const denom = Math.max(1, meta.colors!.length - 1);
      const value = min + ((max - min) * index) / denom;
      return { value, color };
    });
    return {
      title: meta.legend_title ?? "Legend",
      units: meta.units,
      entries,
      opacity,
    };
  }

  return null;
}

export default function App() {
  const [models, setModels] = useState<Option[]>([]);
  const [regions, setRegions] = useState<Option[]>([]);
  const [runs, setRuns] = useState<string[]>([]);
  const [variables, setVariables] = useState<Option[]>([]);
  const [frameRows, setFrameRows] = useState<FrameRow[]>([]);

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

  const frameHours = useMemo(() => frameRows.map((row) => Number(row.fh)).filter(Number.isFinite), [frameRows]);

  const frameByHour = useMemo(() => {
    return new Map(frameRows.map((row) => [Number(row.fh), row]));
  }, [frameRows]);

  const currentFrame = frameByHour.get(forecastHour) ?? frameRows[0] ?? null;
  const overlayResampling = variable === "radar_ptype" ? "nearest" : "linear";

  const runOptions = useMemo<Option[]>(() => {
    return [
      { value: "latest", label: latestRunLabel(runs[0] ?? null) },
      ...runs.map((runId) => ({ value: runId, label: runId })),
    ];
  }, [runs]);

  const tileUrl = useMemo(() => {
    const fallbackFh = frameHours[0] ?? 0;
    return buildTileUrlFromFrame({
      model,
      region,
      run,
      varKey: variable,
      fh: Number.isFinite(forecastHour) ? forecastHour : fallbackFh,
      frameRow: currentFrame,
    });
  }, [model, region, run, variable, forecastHour, frameHours, currentFrame]);

  const legend = useMemo(() => {
    const meta = currentFrame?.meta?.meta ?? frameRows[0]?.meta?.meta ?? null;
    return buildLegend(meta, opacity);
  }, [currentFrame, frameRows, opacity]);

  const effectiveRunId = currentFrame?.run ?? (run !== "latest" ? run : runs[0] ?? null);
  const runDateTimeISO = runIdToIso(effectiveRunId);

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
      try {
        const data = await fetchRegions(model);
        if (cancelled) return;
        const options = data.map((id) => ({ value: id, label: makeRegionLabel(id) }));
        setRegions(options);
        const regionIds = options.map((opt) => opt.value);
        const nextRegion = pickPreferred(regionIds, DEFAULTS.region);
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
  }, [model]);

  useEffect(() => {
    if (!model || !region) return;
    let cancelled = false;

    async function loadRunsAndVars() {
      setError(null);
      try {
        const [runData, varData] = await Promise.all([fetchRuns(model, region), fetchVars(model, region, run)]);
        if (cancelled) return;

        setRuns(runData);

        const filteredVars = varData.filter((id) => ALLOWED_VARIABLES.has(id));
        const variableOptions = filteredVars.map((id) => ({ value: id, label: makeVariableLabel(id) }));
        setVariables(variableOptions);

        setRun((prev) => {
          if (prev === "latest") return "latest";
          if (runData.includes(prev)) return prev;
          return "latest";
        });

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
  }, [model, region, run]);

  useEffect(() => {
    if (!model || !region || !variable) return;
    let cancelled = false;

    async function loadFrames() {
      setError(null);
      try {
        const rows = await fetchFrames(model, region, run, variable);
        if (cancelled) return;
        setFrameRows(rows);
        const frames = rows.map((row) => Number(row.fh)).filter(Number.isFinite);
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
  }, [model, region, run, variable]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.hidden || !model || !region || !variable) {
        return;
      }
      fetchFrames(model, region, run, variable)
        .then((rows) => {
          setFrameRows(rows);
          const frames = rows.map((row) => Number(row.fh)).filter(Number.isFinite);
          setForecastHour((prev) => nearestFrame(frames, prev));
          setTargetForecastHour((prev) => nearestFrame(frames, prev));
        })
        .catch(() => {
          // Background refresh should not interrupt active UI.
        });
    }, 30000);

    return () => window.clearInterval(interval);
  }, [model, region, run, variable]);

  useEffect(() => {
    if (!isPlaying || frameHours.length === 0) return;

    const interval = window.setInterval(() => {
      setTargetForecastHour((prev) => {
        const index = frameHours.indexOf(prev);
        if (index < 0) return frameHours[0];
        return frameHours[(index + 1) % frameHours.length];
      });
    }, 700);

    return () => window.clearInterval(interval);
  }, [isPlaying, frameHours]);

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
        disabled={loading || models.length === 0}
      />

      <div className="relative flex-1 overflow-hidden">
        <MapCanvas
          tileUrl={tileUrl}
          region={region}
          opacity={opacity}
          resampling={overlayResampling}
        />

        {error && (
          <div className="absolute left-4 top-4 z-40 flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive shadow-lg backdrop-blur-md">
            <AlertCircle className="h-3.5 w-3.5" />
            {error}
          </div>
        )}

        <MapLegend legend={legend} onOpacityChange={setOpacity} />

        <BottomForecastControls
          forecastHour={forecastHour}
          availableFrames={frameHours}
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
