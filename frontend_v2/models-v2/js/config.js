const isLocalDevHost =
  window.location.hostname === "127.0.0.1" ||
  window.location.hostname === "localhost";
const isLocalDevPort = window.location.port === "8080";

export const API_BASE =
  isLocalDevHost && isLocalDevPort ? "http://127.0.0.1:8002/api/v2" : "https://api.sodakweather.com/api/v2";

export const TILES_BASE =
  isLocalDevHost && isLocalDevPort ? "http://127.0.0.1:8002" : "https://api.sodakweather.com";

export const DEFAULTS = {
  model: "hrrr",
  region: "pnw",
  run: "latest",
  variable: "tmp2m",
  fhStart: 0,
  fhEnd: 18,
  fhStep: 1,
  zoomMin: 5,
  zoomMax: 11,
  center: [47.6, -122.3],
  zoom: 6,
};

export const VARIABLE_LABELS = {
  tmp2m: "Surface Temperature",
  wspd10m: "Wind Speed",
  refc: "Sim Composite Reflectivity",
};

export const VARIABLES = [
  { id: "tmp2m", label: "Surface Temperature" },
  { id: "wspd10m", label: "Wind Speed" },
  { id: "refc", label: "Sim Composite Reflectivity" },
];
