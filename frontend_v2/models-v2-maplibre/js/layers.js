import { API_BASE, DEFAULTS, TILES_BASE } from "./config.js";

const BASEMAP_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors ' +
  '&copy; <a href="https://carto.com/attributions">CARTO</a>';

const CARTO_LIGHT_BASE_TILES = [
  "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
  "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
  "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
  "https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
];

const CARTO_LIGHT_LABEL_TILES = [
  "https://a.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
  "https://b.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
  "https://c.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
  "https://d.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
];

function baseRoot() {
  const baseCandidate = TILES_BASE || API_BASE || "https://api.sodakweather.com";
  return baseCandidate.replace(/\/?(api\/v2|tiles\/v2)\/?$/i, "");
}

function normalizeTemplatePath(template) {
  if (typeof template !== "string") {
    return "";
  }
  // During parallel migration, nginx is guaranteed to expose /tiles/v2.
  // Canonical /tiles can be enabled later without changing the frontend contract.
  return template.replace(/\/tiles\/(?!v2\/)/, "/tiles/v2/");
}

function toAbsoluteTemplate(template) {
  const normalized = normalizeTemplatePath(template);
  if (!normalized.length) {
    return "";
  }
  if (normalized.startsWith("http://") || normalized.startsWith("https://")) {
    return normalized;
  }
  const root = baseRoot().replace(/\/$/, "");
  const path = normalized.startsWith("/") ? normalized : `/${normalized}`;
  return `${root}${path}`;
}

export function buildTileUrl({ model, region, run = "latest", varKey, fh, frameRow = null }) {
  if (frameRow && typeof frameRow.tile_url_template === "string" && frameRow.tile_url_template.length) {
    return toAbsoluteTemplate(frameRow.tile_url_template);
  }
  const root = baseRoot().replace(/\/$/, "");
  const enc = encodeURIComponent;
  return `${root}/tiles/v2/${enc(model)}/${enc(region)}/${enc(run)}/${enc(varKey)}/${enc(fh)}/{z}/{x}/{y}.png`;
}

export function createMapStyle({ overlayUrl, overlayOpacity = DEFAULTS.overlayOpacity }) {
  return {
    version: 8,
    sources: {
      "twf-basemap": {
        type: "raster",
        tiles: CARTO_LIGHT_BASE_TILES,
        tileSize: 256,
        attribution: BASEMAP_ATTRIBUTION,
      },
      "twf-overlay": {
        type: "raster",
        tiles: [overlayUrl],
        tileSize: 256,
      },
      "twf-labels": {
        type: "raster",
        tiles: CARTO_LIGHT_LABEL_TILES,
        tileSize: 256,
      },
    },
    layers: [
      {
        id: "twf-basemap",
        type: "raster",
        source: "twf-basemap",
      },
      {
        id: "twf-overlay",
        type: "raster",
        source: "twf-overlay",
        minzoom: DEFAULTS.zoomMin,
        maxzoom: DEFAULTS.zoomMax,
        paint: {
          "raster-opacity": overlayOpacity,
          "raster-resampling": "nearest",
        },
      },
      {
        id: "twf-labels",
        type: "raster",
        source: "twf-labels",
      },
    ],
  };
}

export function setOverlayTiles(map, tileUrl) {
  const source = map.getSource("twf-overlay");
  if (!source) {
    return;
  }
  if (typeof source.setTiles === "function") {
    source.setTiles([tileUrl]);
    return;
  }

  // Fallback for environments that do not expose setTiles on raster sources.
  if (map.getLayer("twf-overlay")) {
    map.removeLayer("twf-overlay");
  }
  map.removeSource("twf-overlay");
  map.addSource("twf-overlay", {
    type: "raster",
    tiles: [tileUrl],
    tileSize: 256,
  });
  map.addLayer(
    {
      id: "twf-overlay",
      type: "raster",
      source: "twf-overlay",
      minzoom: DEFAULTS.zoomMin,
      maxzoom: DEFAULTS.zoomMax,
      paint: {
        "raster-opacity": DEFAULTS.overlayOpacity,
        "raster-resampling": "nearest",
      },
    },
    "twf-labels"
  );
}

export function setOverlayOpacity(map, opacity) {
  if (!map.getLayer("twf-overlay")) {
    return;
  }
  map.setPaintProperty("twf-overlay", "raster-opacity", opacity);
}
