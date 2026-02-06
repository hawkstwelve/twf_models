import { API_BASE, DEFAULTS } from "./config.js?v=20260206-1735";
import { applyFramesToSlider, initControls } from "./controls.js?v=20260206-1735";
import { buildTileUrl, createBaseLayer, createLabelLayer, createOverlayLayer } from "./layers.js?v=20260206-1735";

console.debug("modules loaded ok");

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
  overlay: null,
  playTimer: null,
};

const map = L.map("map", {
  minZoom: 3,
  maxZoom: DEFAULTS.zoomMax,
  zoomControl: true,
}).setView(DEFAULTS.center, DEFAULTS.zoom);

map.createPane("basemap");
map.getPane("basemap").style.zIndex = "200";
map.createPane("overlay");
map.getPane("overlay").style.zIndex = "400";
map.createPane("labels");
map.getPane("labels").style.zIndex = "600";

console.log("map init ok");

createBaseLayer({ pane: "basemap", zIndex: 200 }).addTo(map);

state.overlay = createOverlayLayer({
  model: state.model,
  region: state.region,
  run: state.run,
  varKey: state.varKey,
  fh: state.fh,
  pane: "overlay",
  zIndex: 400,
});
state.overlay.addTo(map);

createLabelLayer({ pane: "labels", zIndex: 600 }).addTo(map);

const opacitySlider = document.querySelector('.control-group.stub input[type="range"]');
if (opacitySlider) {
  opacitySlider.disabled = false;
  opacitySlider.value = Math.round((state.overlay.options.opacity ?? 0.55) * 100).toString();
  opacitySlider.addEventListener("input", (event) => {
    const value = Number(event.target.value) / 100;
    state.overlay.setOpacity(value);
  });
}

function updateOverlayUrl() {
  const url = buildTileUrl({
    model: asId(state.model),
    region: asId(state.region),
    run: asId(state.run),
    varKey: asId(state.varKey),
    fh: state.fh,
  });
  console.debug("tile url", url);
  state.overlay.setUrl(url);
  state.overlay.redraw();
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
    if (idx >= 0) {
      slider.value = idx.toString();
    } else {
      slider.value = "0";
    }
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

  const legend_stops = meta?.legend_stops;
  if (!Array.isArray(legend_stops) || legend_stops.length < 2) {
    console.warn("renderLegendStepped called but legend_stops invalid");
    return;
  }

  // Set title
  if (legendTitle) {
    const title = meta.legend_title || meta.units || "";
    legendTitle.textContent = title;
  }

  // Build vertical list showing EVERY legend_stop value and color
  legendContainer.innerHTML = "";
  
  // Reverse order so highest values are at top
  for (let i = legend_stops.length - 1; i >= 0; i--) {
    const [value, color] = legend_stops[i];
    const item = document.createElement("div");
    item.className = "legend-item";
    
    const colorBox = document.createElement("div");
    colorBox.className = "legend-color-box";
    colorBox.style.backgroundColor = color;
    
    const label = document.createElement("span");
    label.className = "legend-label";
    
    // Show each exact threshold value
    const formattedValue = Number.isInteger(Number(value)) ? value : Number(value).toFixed(1);
    if (i === legend_stops.length - 1) {
      // Highest value
      label.textContent = `≥ ${formattedValue}`;
    } else {
      label.textContent = formattedValue;
    }
    
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
    if (legendTitle) legendTitle.textContent = "";
    return;
  }

  // Set title
  if (legendTitle) {
    const title = meta.legend_title || meta.units || "";
    legendTitle.textContent = title;
  }

  // For continuous gradients, show all colors with individual threshold values
  legendContainer.innerHTML = "";
  
  const [minVal, maxVal] = range;
  const numStops = colors.length; // Show all colors in the palette
  
  // Create stops from colors array, reversed so highest is at top
  for (let i = numStops - 1; i >= 0; i--) {
    const item = document.createElement("div");
    item.className = "legend-item";
    
    const colorBox = document.createElement("div");
    colorBox.className = "legend-color-box";
    colorBox.style.backgroundColor = colors[i];
    
    const value = minVal + ((maxVal - minVal) * i / (numStops - 1));
    const label = document.createElement("span");
    label.className = "legend-label";
    
    // Show individual threshold values
    if (i === numStops - 1) {
      // Highest value
      label.textContent = `≥ ${Number.isFinite(value) ? value.toFixed(0) : ""}`;
    } else {
      label.textContent = Number.isFinite(value) ? value.toFixed(0) : "";
    }
    
    item.appendChild(colorBox);
    item.appendChild(label);
    legendContainer.appendChild(item);
  }
}

function renderLegend(meta) {
  const legendContainer = document.querySelector(".legend-items");
  const legendTitle = document.querySelector(".legend-title");
  
  if (!meta) {
    if (legendContainer) legendContainer.innerHTML = "";
    if (legendTitle) legendTitle.textContent = "";
    return;
  }

  // Use legend_stops if present (not "stops")
  const legend_stops = meta.legend_stops;
  if (Array.isArray(legend_stops) && legend_stops.length >= 2) {
    renderLegendStepped(meta);
  } else {
    renderLegendGradient(meta);
  }
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
  renderLegend(metadata.legendMeta);
  const preferred = Number.isFinite(metadata.preferredFh) ? metadata.preferredFh : null;
  const nextFh = preferred ?? (state.frames.length ? state.frames[0] : DEFAULTS.fhStart);
  applyFramesToSlider(state.frames, nextFh);
  setForecastHour(nextFh, { userInitiated });
  updateOverlayUrl();
}

async function bootstrap() {
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
  const lat = event.latlng.lat.toFixed(4);
  const lon = event.latlng.lng.toFixed(4);
  info.textContent = `Lat: ${lat}, Lon: ${lon}`;
});
