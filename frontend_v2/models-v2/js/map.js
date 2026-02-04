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

function renderLegend(meta) {
  const legendBar = document.querySelector(".legend-bar");
  const legendLabels = document.querySelector(".legend-labels");
  if (!legendBar || !legendLabels) {
    return;
  }

  const stops = Array.isArray(meta?.stops) ? meta.stops : null;
  const colors = Array.isArray(meta?.colors) ? meta.colors : null;
  const levels = Array.isArray(meta?.levels) ? meta.levels : null;
  const kind = meta?.kind ? String(meta.kind) : "continuous";

  if ((!stops || stops.length < 2) && (!colors || colors.length < 2)) {
    legendBar.style.background = "#ccc";
    legendLabels.innerHTML = "";
    return;
  }

  let range = Array.isArray(meta.range) ? meta.range : [0, 1];
  const units = meta.units ? String(meta.units) : "";

  let gradient = "";
  if ((kind === "discrete" || levels) && levels && colors && colors.length) {
    const numericLevels = levels.map((value) => Number(value)).filter(Number.isFinite);
    if (numericLevels.length >= 2) {
      range = [Math.min(...numericLevels), Math.max(...numericLevels)];
    }
    const [minVal, maxVal] = range.map((value) => Number(value));
    const span = Number.isFinite(minVal) && Number.isFinite(maxVal) && maxVal !== minVal
      ? maxVal - minVal
      : 1;
    const stopParts = [];
    const intervalCount = Math.min(colors.length, levels.length - 1);
    for (let idx = 0; idx < intervalCount; idx += 1) {
      const startVal = Number(levels[idx]);
      const endVal = Number(levels[idx + 1]);
      const startPct = Number.isFinite(startVal)
        ? Math.max(0, Math.min(100, ((startVal - minVal) / span) * 100))
        : 0;
      const endPct = Number.isFinite(endVal)
        ? Math.max(0, Math.min(100, ((endVal - minVal) / span) * 100))
        : startPct;
      const color = colors[idx] ?? colors[colors.length - 1];
      stopParts.push(`${color} ${startPct.toFixed(2)}%`, `${color} ${endPct.toFixed(2)}%`);
    }
    gradient = `linear-gradient(to top, ${stopParts.join(", ")})`;
  } else if (stops && stops.length >= 2) {
    const values = stops.map((item) => Number(item[0])).filter(Number.isFinite);
    if (values.length >= 2) {
      range = [Math.min(...values), Math.max(...values)];
    }
    const [minVal, maxVal] = range.map((value) => Number(value));
    const span = Number.isFinite(minVal) && Number.isFinite(maxVal) && maxVal !== minVal
      ? maxVal - minVal
      : 1;
    const stopParts = stops.map(([value, color]) => {
      const numericValue = Number(value);
      const pct = Number.isFinite(numericValue)
        ? Math.max(0, Math.min(100, ((numericValue - minVal) / span) * 100))
        : 0;
      return `${color} ${pct.toFixed(2)}%`;
    });
    gradient = `linear-gradient(to top, ${stopParts.join(", ")})`;
  } else if (colors) {
    gradient = `linear-gradient(to top, ${colors.join(", ")})`;
  }
  legendBar.style.background = gradient;

  const minVal = Number(range[0]);
  const maxVal = Number(range[1]);
  const minLabel = Number.isFinite(minVal) ? minVal : range[0];
  const maxLabel = Number.isFinite(maxVal) ? maxVal : range[1];

  legendLabels.innerHTML = "";
  const title = document.createElement("div");
  title.className = "legend-units";
  title.textContent = units ? `${units} (${kind})` : kind;
  legendLabels.appendChild(title);

  if ((kind === "discrete" || levels) && levels && levels.length) {
    const numericLevels = levels.map((value) => Number(value)).filter(Number.isFinite);
    const ticks = numericLevels.length ? numericLevels : levels;
    const maxTicks = 8;
    const step = ticks.length > maxTicks ? Math.ceil(ticks.length / maxTicks) : 1;
    for (let idx = ticks.length - 1; idx >= 0; idx -= step) {
      const tick = document.createElement("span");
      tick.textContent = `${ticks[idx]}`;
      legendLabels.appendChild(tick);
    }
  } else {
    const maxTick = document.createElement("span");
    maxTick.textContent = `${maxLabel}`;
    const minTick = document.createElement("span");
    minTick.textContent = `${minLabel}`;
    legendLabels.appendChild(maxTick);
    legendLabels.appendChild(minTick);
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
