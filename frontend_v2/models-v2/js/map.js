import { API_BASE, DEFAULTS } from "./config.js?v=20260204-2115";
import { applyFramesToSlider, initControls, normalizeFrames } from "./controls.js?v=20260204-2115";
import { buildTileUrl, createBaseLayer, createLabelLayer, createOverlayLayer } from "./layers.js?v=20260204-2115";

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

function setVariable(variable) {
  state.varKey = variable;
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
  slider.value = value.toString();
  display.textContent = `FH: ${value}`;
}

function renderLegendStepped(meta) {
  const legendBar = document.querySelector(".legend-bar");
  const legendTicks = document.querySelector(".legend-ticks");
  const legendTitle = document.querySelector(".legend-title");
  
  if (!legendBar || !legendTicks) {
    return;
  }

  const legend_stops = meta?.legend_stops;
  if (!Array.isArray(legend_stops) || legend_stops.length < 2) {
    console.warn("renderLegendStepped called but legend_stops invalid");
    return;
  }

  // Build stepped gradient with hard boundaries (no blending)
  const values = legend_stops.map(([val]) => Number(val)).filter(Number.isFinite);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const span = maxVal - minVal || 1;

  const segments = [];
  for (let i = 0; i < legend_stops.length - 1; i++) {
    const [val1, color1] = legend_stops[i];
    const [val2] = legend_stops[i + 1];
    const startPct = ((Number(val1) - minVal) / span) * 100;
    const endPct = ((Number(val2) - minVal) / span) * 100;
    // Hard edge: repeat color at both boundaries
    segments.push(`${color1} ${startPct.toFixed(2)}%`, `${color1} ${endPct.toFixed(2)}%`);
  }
  const gradient = `linear-gradient(to right, ${segments.join(", ")})`;
  legendBar.style.background = gradient;

  // Render tick labels
  legendTicks.innerHTML = "";
  const maxTicks = 15; // Show all stops for wspd10m (27 stops), but cap others
  const step = legend_stops.length > maxTicks ? Math.ceil(legend_stops.length / maxTicks) : 1;
  
  legend_stops.forEach(([value, color], idx) => {
    if (idx % step !== 0 && idx !== legend_stops.length - 1) {
      return; // Skip non-step ticks except last
    }
    const tick = document.createElement("div");
    tick.className = "legend-tick";
    const pct = ((Number(value) - minVal) / span) * 100;
    tick.style.left = `${pct}%`;
    
    const label = document.createElement("span");
    label.className = "legend-tick-label";
    label.textContent = Number.isInteger(Number(value)) ? value : Number(value).toFixed(1);
    tick.appendChild(label);
    
    legendTicks.appendChild(tick);
  });

  // Set legend title
  if (legendTitle) {
    const title = meta.legend_title || meta.units || "";
    legendTitle.textContent = title;
  }
}

function renderLegendGradient(meta) {
  const legendBar = document.querySelector(".legend-bar");
  const legendTicks = document.querySelector(".legend-ticks");
  const legendTitle = document.querySelector(".legend-title");
  
  if (!legendBar || !legendTicks) {
    return;
  }

  const colors = Array.isArray(meta?.colors) ? meta.colors : null;
  if (!colors || colors.length < 2) {
    legendBar.style.background = "#ccc";
    legendTicks.innerHTML = "";
    if (legendTitle) legendTitle.textContent = "";
    return;
  }

  // Build smooth gradient from colors
  const gradient = `linear-gradient(to right, ${colors.join(", ")})`;
  legendBar.style.background = gradient;

  // Render min/max ticks
  const range = Array.isArray(meta.range) ? meta.range : [0, 1];
  const [minVal, maxVal] = range;

  legendTicks.innerHTML = "";
  
  const minTick = document.createElement("div");
  minTick.className = "legend-tick";
  minTick.style.left = "0%";
  const minLabel = document.createElement("span");
  minLabel.className = "legend-tick-label";
  minLabel.textContent = Number.isFinite(minVal) ? minVal.toFixed(0) : minVal;
  minTick.appendChild(minLabel);
  legendTicks.appendChild(minTick);

  const maxTick = document.createElement("div");
  maxTick.className = "legend-tick";
  maxTick.style.left = "100%";
  const maxLabel = document.createElement("span");
  maxLabel.className = "legend-tick-label";
  maxLabel.textContent = Number.isFinite(maxVal) ? maxVal.toFixed(0) : maxVal;
  maxTick.appendChild(maxLabel);
  legendTicks.appendChild(maxTick);

  // Set legend title
  if (legendTitle) {
    const title = meta.legend_title || meta.units || "";
    legendTitle.textContent = title;
  }
}

function renderLegend(meta) {
  if (!meta) {
    const legendBar = document.querySelector(".legend-bar");
    const legendTicks = document.querySelector(".legend-ticks");
    const legendTitle = document.querySelector(".legend-title");
    if (legendBar) legendBar.style.background = "#ccc";
    if (legendTicks) legendTicks.innerHTML = "";
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

async function fetchFrames({ model, region, varKey }) {
  try {
    const response = await fetch(
      `${API_BASE}/${model}/${region}/latest/${varKey}/frames`,
      { credentials: "omit" }
    );
    if (!response.ok) {
      throw new Error(`Frames request failed: ${response.status}`);
    }
    const payload = await response.json();
    const filtered = Array.isArray(payload)
      ? payload.filter((row) => row && row.has_cog)
      : [];
    const frames = normalizeFrames(filtered);
    const legendMeta = filtered.length ? filtered[0]?.meta?.meta ?? null : null;
    return { frames, legendMeta };
  } catch (error) {
    console.warn("Failed to refresh frames list", error);
    return { frames: [], legendMeta: null };
  }
}

async function bootstrap() {
  const metadata = await initControls({
    onVariableChange: async (value) => {
      setVariable(value);
      const result = await fetchFrames({
        model: state.model,
        region: state.region,
        varKey: value,
      });
      state.frames = result.frames;
      const nextFh = state.frames.length ? state.frames[0] : DEFAULTS.fhStart;
      applyFramesToSlider(state.frames, nextFh);
      setForecastHour(nextFh, { userInitiated: true });
      renderLegend(result.legendMeta);
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

  if (metadata) {
    state.model = asId(metadata.model);
    state.region = asId(metadata.region);
    state.run = asId(metadata.run);
    state.varKey = asId(metadata.varKey);
    state.frames = metadata.frames;
    renderLegend(metadata.legendMeta);
    const varSelect = document.getElementById("var-select");
    if (varSelect) {
      const nextVar = state.varKey || DEFAULTS.variable;
      if (nextVar) {
        varSelect.value = nextVar;
      }
    }
    const initialFh = state.frames.length ? state.frames[0] : state.fh;
    setForecastHour(initialFh);
    applyFramesToSlider(state.frames, initialFh);
    updateOverlayUrl();
  }
}

bootstrap();

map.on("click", (event) => {
  const info = document.getElementById("click-info");
  const lat = event.latlng.lat.toFixed(4);
  const lon = event.latlng.lng.toFixed(4);
  info.textContent = `Lat: ${lat}, Lon: ${lon}`;
});
