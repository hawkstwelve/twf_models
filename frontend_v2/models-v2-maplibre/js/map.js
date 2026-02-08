import { DEFAULTS } from "./config.js";
import { applyFramesToSlider, initControls } from "./controls.js";
import { buildTileUrl, createMapStyle, setOverlayOpacity, setOverlayTiles } from "./layers.js";

function asId(value) {
  if (value && typeof value === "object") {
    return value.id ?? value.value ?? value.name ?? "";
  }
  return value ?? "";
}

const state = {
  model: DEFAULTS.model,
  region: DEFAULTS.region,
  run: DEFAULTS.run,
  varKey: DEFAULTS.variable,
  fh: DEFAULTS.fhStart,
  frames: [],
  frameRowsByFh: new Map(),
  playTimer: null,
  overlayOpacity: DEFAULTS.overlayOpacity,
};

let mapReady = false;
let pendingTileUrl = buildTileUrl({
  model: state.model,
  region: state.region,
  run: state.run,
  varKey: state.varKey,
  fh: state.fh,
});

const map = new maplibregl.Map({
  container: "map",
  style: createMapStyle({
    overlayUrl: pendingTileUrl,
    overlayOpacity: state.overlayOpacity,
  }),
  center: [DEFAULTS.center[1], DEFAULTS.center[0]],
  zoom: DEFAULTS.zoom,
  minZoom: 3,
  maxZoom: DEFAULTS.zoomMax,
});

map.addControl(new maplibregl.NavigationControl(), "top-left");

map.on("load", () => {
  mapReady = true;
  if (pendingTileUrl) {
    setOverlayTiles(map, pendingTileUrl);
    setOverlayOpacity(map, state.overlayOpacity);
  }
});

function currentFrameRow() {
  return state.frameRowsByFh.get(state.fh) ?? null;
}

function updateOverlayUrl() {
  const url = buildTileUrl({
    model: asId(state.model),
    region: asId(state.region),
    run: asId(state.run),
    varKey: asId(state.varKey),
    fh: state.fh,
    frameRow: currentFrameRow(),
  });
  pendingTileUrl = url;
  if (mapReady) {
    setOverlayTiles(map, url);
    setOverlayOpacity(map, state.overlayOpacity);
  }
}

function setForecastHour(fh, { userInitiated = false } = {}) {
  if (userInitiated && state.playTimer) {
    stopPlayback();
    const playToggle = document.getElementById("play-toggle");
    playToggle.dataset.playing = "false";
    playToggle.textContent = "Play";
  }
  state.fh = fh;
  updateOverlayUrl();
}

function startPlayback() {
  stopPlayback();
  state.playTimer = window.setInterval(() => {
    if (!state.frames.length) {
      const next = state.fh + DEFAULTS.fhStep;
      if (next > DEFAULTS.fhEnd) {
        setForecastHour(DEFAULTS.fhStart);
        updateSlider(DEFAULTS.fhStart);
        return;
      }
      setForecastHour(next);
      updateSlider(next);
      return;
    }
    const currentIndex = state.frames.indexOf(state.fh);
    const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % state.frames.length : 0;
    const nextFh = state.frames[nextIndex];
    setForecastHour(nextFh);
    updateSlider(nextFh);
  }, 700);
}

function stopPlayback() {
  if (state.playTimer) {
    window.clearInterval(state.playTimer);
    state.playTimer = null;
  }
}

function updateSlider(value) {
  const slider = document.getElementById("fh-slider");
  const display = document.getElementById("fh-display");
  if (!slider || !display) {
    return;
  }
  if (slider.dataset.mode === "index" && Array.isArray(state.frames) && state.frames.length) {
    const idx = state.frames.indexOf(value);
    slider.value = idx >= 0 ? idx.toString() : "0";
  } else {
    slider.value = value.toString();
  }
  display.textContent = `FH: ${value}`;
}

function renderLegendStepped(meta) {
  const legendContainer = document.querySelector(".legend-items");
  const legendTitle = document.querySelector(".legend-title");

  if (!legendContainer) {
    return;
  }

  const legendStops = meta?.legend_stops;
  if (!Array.isArray(legendStops) || legendStops.length < 2) {
    return;
  }

  if (legendTitle) {
    const title = meta.legend_title || meta.units || "";
    legendTitle.textContent = title;
  }

  legendContainer.innerHTML = "";
  for (let i = legendStops.length - 1; i >= 0; i -= 1) {
    const [value, color] = legendStops[i];
    const item = document.createElement("div");
    item.className = "legend-item";

    const colorBox = document.createElement("div");
    colorBox.className = "legend-color-box";
    colorBox.style.backgroundColor = color;

    const label = document.createElement("span");
    label.className = "legend-label";
    const formattedValue = Number.isInteger(Number(value)) ? value : Number(value).toFixed(1);
    label.textContent = i === legendStops.length - 1 ? `>= ${formattedValue}` : `${formattedValue}`;

    item.appendChild(colorBox);
    item.appendChild(label);
    legendContainer.appendChild(item);
  }
}

function renderLegendGradient(meta) {
  const legendContainer = document.querySelector(".legend-items");
  const legendTitle = document.querySelector(".legend-title");

  if (!legendContainer) {
    return;
  }

  const colors = Array.isArray(meta?.colors) ? meta.colors : null;
  const range = Array.isArray(meta?.range) ? meta.range : [0, 1];

  if (!colors || colors.length < 2) {
    legendContainer.innerHTML = "";
    if (legendTitle) {
      legendTitle.textContent = "";
    }
    return;
  }

  if (legendTitle) {
    const title = meta.legend_title || meta.units || "";
    legendTitle.textContent = title;
  }

  legendContainer.innerHTML = "";

  const [minVal, maxVal] = range;
  const numStops = colors.length;
  for (let i = numStops - 1; i >= 0; i -= 1) {
    const item = document.createElement("div");
    item.className = "legend-item";

    const colorBox = document.createElement("div");
    colorBox.className = "legend-color-box";
    colorBox.style.backgroundColor = colors[i];

    const value = minVal + ((maxVal - minVal) * i) / (numStops - 1);
    const label = document.createElement("span");
    label.className = "legend-label";
    label.textContent =
      i === numStops - 1
        ? `>= ${Number.isFinite(value) ? value.toFixed(0) : ""}`
        : `${Number.isFinite(value) ? value.toFixed(0) : ""}`;

    item.appendChild(colorBox);
    item.appendChild(label);
    legendContainer.appendChild(item);
  }
}

function renderLegend(meta) {
  const legendContainer = document.querySelector(".legend-items");
  const legendTitle = document.querySelector(".legend-title");

  if (!meta) {
    if (legendContainer) {
      legendContainer.innerHTML = "";
    }
    if (legendTitle) {
      legendTitle.textContent = "";
    }
    return;
  }

  if (Array.isArray(meta.legend_stops) && meta.legend_stops.length >= 2) {
    renderLegendStepped(meta);
    return;
  }
  renderLegendGradient(meta);
}

function applySelection(metadata, { userInitiated = false } = {}) {
  if (!metadata) {
    return;
  }

  state.model = asId(metadata.model);
  state.region = asId(metadata.region);
  state.run = asId(metadata.run);
  state.varKey = asId(metadata.varKey);
  state.frames = metadata.frames ?? [];
  const rows = Array.isArray(metadata.frameRows) ? metadata.frameRows : [];
  state.frameRowsByFh = new Map(rows.map((row) => [Number(row.fh), row]));

  renderLegend(metadata.legendMeta);

  const preferred = Number.isFinite(metadata.preferredFh) ? metadata.preferredFh : null;
  const nextFh = preferred ?? (state.frames.length ? state.frames[0] : DEFAULTS.fhStart);

  applyFramesToSlider(state.frames, nextFh);
  setForecastHour(nextFh, { userInitiated });
}

async function bootstrap() {
  const opacitySlider = document.getElementById("opacity-slider");
  if (opacitySlider) {
    opacitySlider.value = Math.round(state.overlayOpacity * 100).toString();
    opacitySlider.addEventListener("input", (event) => {
      state.overlayOpacity = Number(event.target.value) / 100;
      if (mapReady) {
        setOverlayOpacity(map, state.overlayOpacity);
      }
    });
  }

  const metadata = await initControls({
    onSelectionChange: (next) => {
      applySelection(next, { userInitiated: Boolean(next?.userInitiated) });
    },
    onForecastHourChange: (value) => {
      setForecastHour(value, { userInitiated: true });
    },
    onPlayToggle: (isPlaying) => {
      if (isPlaying) {
        startPlayback();
      } else {
        stopPlayback();
      }
    },
  });

  applySelection(metadata, { userInitiated: Boolean(metadata?.userInitiated) });
}

bootstrap();

map.on("click", (event) => {
  const info = document.getElementById("click-info");
  const lat = event.lngLat.lat.toFixed(4);
  const lon = event.lngLat.lng.toFixed(4);
  info.textContent = `Lat: ${lat}, Lon: ${lon}`;
});
