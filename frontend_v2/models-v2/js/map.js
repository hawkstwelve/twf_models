import { API_BASE, DEFAULTS } from "./config.js?v=20260204-2031";
import { applyFramesToSlider, initControls } from "./controls.js?v=20260204-2031";
import { buildTileUrl, createBaseLayer, createLabelLayer, createOverlayLayer } from "./layers.js?v=20260204-2031";

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
  state.overlay.setUrl(url, true);
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
    return payload
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value))
      .sort((a, b) => a - b);
  } catch (error) {
    console.warn("Failed to refresh frames list", error);
    return [];
  }
}

async function bootstrap() {
  const metadata = await initControls({
    onVariableChange: async (value) => {
      setVariable(value);
      const frames = await fetchFrames({
        model: state.model,
        region: state.region,
        varKey: value,
      });
      state.frames = frames;
      const nextFh = frames.length ? frames[0] : DEFAULTS.fhStart;
      applyFramesToSlider(frames, nextFh);
      setForecastHour(nextFh, { userInitiated: true });
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
