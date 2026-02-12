const isLocalDevHost =
  window.location.hostname === "127.0.0.1" ||
  window.location.hostname === "localhost";

const isLocalDevPort =
  window.location.port === "5173" ||
  window.location.port === "4173" ||
  window.location.port === "8080";

function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

const configuredApiBaseUrl = String(import.meta.env.VITE_API_BASE_URL ?? "").trim();
const defaultApiBaseUrl = import.meta.env.PROD
  ? "https://api.sodakweather.com"
  : isLocalDevHost && isLocalDevPort
    ? "http://127.0.0.1:8099"
    : "https://api.sodakweather.com";

export const API_BASE_URL = normalizeBaseUrl(configuredApiBaseUrl || defaultApiBaseUrl);

export function absolutizeUrl(pathOrUrl: string): string {
  const candidate = pathOrUrl.trim();
  if (!candidate) {
    return API_BASE_URL;
  }
  if (candidate.startsWith("http://") || candidate.startsWith("https://")) {
    return candidate;
  }
  if (candidate.startsWith("/")) {
    return `${API_BASE_URL}${candidate}`;
  }
  return `${API_BASE_URL}/${candidate}`;
}

export const API_BASE = absolutizeUrl("/api");
export const API_V2_BASE = absolutizeUrl("/api/v2");
export const TILES_BASE = API_BASE_URL;

export const DEFAULTS = {
  model: "hrrr",
  region: "published",
  run: "latest",
  variable: "tmp2m",
  center: [47.6, -122.3] as [number, number],
  zoom: 6,
  overlayOpacity: 0.85,
};

export const FORCE_LEGACY_RUNTIME = String(import.meta.env.VITE_FORCE_LEGACY_OVERLAYS ?? "")
  .trim()
  .toLowerCase() === "true";

export const ALLOWED_VARIABLES = new Set(["tmp2m", "wspd10m", "radar_ptype", "precip_ptype", "qpf6h"]);

export const VARIABLE_LABELS: Record<string, string> = {
  tmp2m: "Surface Temperature",
  wspd10m: "Wind Speed",
  radar_ptype: "Composite Reflectivity + P-Type",
  precip_ptype: "Precip + Type",
  qpf6h: "6-hr Precip",
};
