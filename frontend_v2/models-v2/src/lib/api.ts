import { API_BASE, absolutizeUrl } from "@/lib/config";

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

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(absolutizeUrl(url), { credentials: "omit" });
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

export async function fetchRunManifest(model: string, run: string): Promise<OfflineRunManifest> {
  const runKey = run || "latest";
  return fetchJson<OfflineRunManifest>(
    `${API_BASE}/run/${encodeURIComponent(model)}/${encodeURIComponent(runKey)}/manifest.json`
  );
}
