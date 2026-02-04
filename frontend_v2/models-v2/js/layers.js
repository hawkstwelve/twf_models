import { API_BASE, DEFAULTS, TILES_BASE } from "./config.js";

const BASEMAP_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors ' +
  '&copy; <a href="https://carto.com/attributions">CARTO</a>';

export function createBaseLayer({ pane = "basemap", zIndex = 200 } = {}) {
  return L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    {
      attribution: BASEMAP_ATTRIBUTION,
      subdomains: "abcd",
      maxZoom: 20,
      pane,
      zIndex,
    }
  );
}

export function createLabelLayer({ pane = "labels", zIndex = 600 } = {}) {
  return L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png",
    {
      attribution: BASEMAP_ATTRIBUTION,
      subdomains: "abcd",
      maxZoom: 20,
      pane,
      zIndex,
    }
  );
}

/**
 * Build the backend tile URL for model overlays
 */
export function buildTileUrl({ model, region, run = "latest", varKey, fh, z = "{z}", x = "{x}", y = "{y}" }) {
  const baseCandidate = TILES_BASE || API_BASE || "https://api.sodakweather.com";
  const base = baseCandidate.replace(/\/?(api\/v2|tiles\/v2)\/?$/i, "");
  const enc = encodeURIComponent;
  return `${base}/tiles/v2/${enc(model)}/${enc(region)}/${enc(run)}/${enc(varKey)}/${enc(fh)}/${z}/${x}/${y}.png`;
}

/**
 * Create the Leaflet overlay layer
 */
export function createOverlayLayer({ model, region, run, varKey, fh, pane = "overlay", zIndex = 400 }) {
  const url = buildTileUrl({ model, region, run, varKey, fh });

  return L.tileLayer(url, {
    minZoom: DEFAULTS.zoomMin,
    maxZoom: DEFAULTS.zoomMax,
    opacity: 0.55,
    tileSize: 256,
    maxNativeZoom: 9,
    pane,
    zIndex,
    className: "twf-overlay-title",

    // Performance / UX
    keepBuffer: 4,
    updateWhenIdle: true,
    updateWhenZooming: false,

    // Required for future canvas operations (legends, screenshots)
    crossOrigin: true,
  });
}