import { API_BASE, DEFAULTS } from "./config.js";

const BASEMAP_ATTRIBUTION =
  "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors &copy; <a href=\"https://carto.com/attributions\">CARTO</a>";

export function createBaseLayer() {
  return L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    {
      attribution: BASEMAP_ATTRIBUTION,
      subdomains: "abcd",
      maxZoom: 20,
    }
  );
}

export function buildOverlayUrl({ model, run, variable, fh }) {
  return `${API_BASE}/tiles/v2/${model}/${run}/${variable}/${fh}/{z}/{x}/{y}.png`;
}

export function createOverlayLayer({ model, run, variable, fh }) {
  const url = buildOverlayUrl({ model, run, variable, fh });

  return L.tileLayer(url, {
    minZoom: DEFAULTS.zoomMin,
    maxZoom: DEFAULTS.zoomMax,
    opacity: 1,
    keepBuffer: 4,
    updateWhenIdle: true,
    updateWhenZooming: false,
    tileSize: 256,
  });
}
