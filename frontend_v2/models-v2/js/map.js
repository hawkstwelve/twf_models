import { DEFAULTS } from "./config.js";
import { initControls } from "./controls.js";
import { buildOverlayUrl, createBaseLayer, createOverlayLayer } from "./layers.js";

const state = {
  model: DEFAULTS.model,
  run: DEFAULTS.run,
  variable: DEFAULTS.variable,
  fh: DEFAULTS.fhStart,
  overlay: null,
  playTimer: null,
};

const map = L.map("map", {
  minZoom: 3,
  maxZoom: DEFAULTS.zoomMax,
  zoomControl: true,
}).setView(DEFAULTS.center, DEFAULTS.zoom);

createBaseLayer().addTo(map);

state.overlay = createOverlayLayer({
  model: state.model,
  run: state.run,
  variable: state.variable,
  fh: state.fh,
});
state.overlay.addTo(map);

function updateOverlayUrl() {
  const url = buildOverlayUrl({
    model: state.model,
    run: state.run,
    variable: state.variable,
    fh: state.fh,
  });
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
  state.variable = variable;
  updateOverlayUrl();
}

function startPlayback() {
  stopPlayback();
  state.playTimer = window.setInterval(() => {
    const next = state.fh + DEFAULTS.fhStep;
    if (next > DEFAULTS.fhEnd) {
      setForecastHour(DEFAULTS.fhStart);
      updateSlider(DEFAULTS.fhStart);
      return;
    }
    setForecastHour(next);
    updateSlider(next);
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
  slider.value = value.toString();
  display.textContent = `FH: ${value}`;
}

initControls({
  onVariableChange: setVariable,
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

map.on("click", (event) => {
  const info = document.getElementById("click-info");
  const lat = event.latlng.lat.toFixed(4);
  const lon = event.latlng.lng.toFixed(4);
  info.textContent = `Lat: ${lat}, Lon: ${lon}`;
});
