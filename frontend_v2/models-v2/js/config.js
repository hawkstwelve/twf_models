const isLocalDevHost =
  window.location.hostname === "127.0.0.1" ||
  window.location.hostname === "localhost";
const isLocalDevPort = window.location.port === "8080";

export const API_BASE =
  isLocalDevHost && isLocalDevPort ? "http://127.0.0.1:8002" : "";

export const DEFAULTS = {
  model: "hrrr",
  run: "testrun",
  variable: "tmp2m",
  fhStart: 0,
  fhEnd: 18,
  fhStep: 1,
  zoomMin: 5,
  zoomMax: 11,
  center: [47.6, -122.3],
  zoom: 6,
};

// TODO: Replace hardcoded runs/vars/frames with API metadata.
export const VARIABLES = [
  { id: "tmp2m", label: "2m Temperature" },
];
