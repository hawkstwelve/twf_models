import { API_BASE, DEFAULTS, absolutizeUrl } from "@/lib/config";

export type ModelOption = {
  id: string;
  name: string;
};

export type LegendStops = [number | string, string][];

export type LegendMeta = {
  kind?: string;
  display_name?: string;
  legend_title?: string;
  units?: string;
  legend_stops?: LegendStops;
  colors?: string[];
  levels?: number[];
  ptype_order?: string[];
  ptype_breaks?: Record<string, { offset: number; count: number }>;
  ptype_levels?: Record<string, number[]>;
  range?: [number, number];
  bins_per_ptype?: number;
};

export type OfflineManifestFrame = {
  frame_id: string;
  fhr: number;
  valid_time: string;
  url: string;
  frame_image_url?: string;
  frame_image_version?: string;
  image_url?: string;
};

export type OfflineVariableManifest = {
  contract_version: number;
  model: string;
  run: string;
  variable: string;
  expected_frames: number;
  available_frames: number;
  frames: OfflineManifestFrame[];
  last_updated: string;
};

export type OfflineRunManifest = {
  contract_version: number;
  model: string;
  run: string;
  variables: Record<string, OfflineVariableManifest>;
  last_updated: string;
};

export type VarRow =
  | string
  | {
      id: string;
      display_name?: string;
      name?: string;
      label?: string;
    };

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(absolutizeUrl(url), {
    credentials: "omit",
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchModels(): Promise<ModelOption[]> {
  return fetchJson<ModelOption[]>(`${API_BASE}/models`);
}

export async function fetchRuns(model: string): Promise<string[]> {
  return fetchJson<string[]>(`${API_BASE}/runs?model=${encodeURIComponent(model)}`);
}

export async function fetchVars(model: string, run: string): Promise<VarRow[]> {
  const runKey = run || "latest";
  const vars = await fetchJson<string[]>(
    `${API_BASE}/vars?model=${encodeURIComponent(model)}&run=${encodeURIComponent(runKey)}`
  );
  return vars;
}

/**
 * Module-level early manifest prefetch.  Starts the network request for the
 * default model+run manifest the moment this module is evaluated — well
 * before React mounts and effects fire — shaving the React-mount latency
 * off the critical path for the initial overlay.
 */
const _earlyManifestUrl =
  `${API_BASE}/run/${encodeURIComponent(DEFAULTS.model)}/${encodeURIComponent(DEFAULTS.run)}/manifest.json`;
let _earlyManifestPromise: Promise<OfflineRunManifest> | null =
  fetchJson<OfflineRunManifest>(_earlyManifestUrl, { cache: "no-cache" });

export async function fetchRunManifest(model: string, run: string): Promise<OfflineRunManifest> {
  const runKey = run || "latest";

  // If this is the very first call for the default model+run, re-use the
  // module-level prefetch promise instead of issuing a duplicate request.
  if (_earlyManifestPromise) {
    const isDefault =
      model === DEFAULTS.model &&
      (runKey === DEFAULTS.run || runKey === "latest");
    if (isDefault) {
      const promise = _earlyManifestPromise;
      _earlyManifestPromise = null;           // consume once
      return promise;
    }
    // Different model/run requested first — discard early prefetch.
    _earlyManifestPromise = null;
  }

  // Manifest must always be fresh (progressive publishing can change it
  // at any moment), so bypass the browser cache.
  return fetchJson<OfflineRunManifest>(
    `${API_BASE}/run/${encodeURIComponent(model)}/${encodeURIComponent(runKey)}/manifest.json`,
    { cache: "no-cache" },
  );
}
