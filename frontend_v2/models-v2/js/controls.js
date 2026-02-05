import { API_BASE, DEFAULTS, VARIABLE_LABELS, VARIABLES } from "./config.js";

async function fetchJson(url) {
  const response = await fetch(url, { credentials: "omit" });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export function normalizeFrames(frames) {
  if (!Array.isArray(frames)) {
    return [];
  }
  return frames
    .map((value) => {
      if (value && typeof value === "object") {
        return Number(value.fh ?? value.value ?? value.id ?? value.name ?? value);
      }
      return Number(value);
    })
    .filter((value) => Number.isFinite(value))
    .sort((a, b) => a - b);
}

function asId(value) {
  if (value && typeof value === "object") {
    return value.id ?? value.value ?? value.name ?? "";
  }
  return value ?? "";
}

function asLabel(value) {
  if (value && typeof value === "object") {
    return value.label ?? value.name ?? value.id ?? value.value ?? "";
  }
  return value ?? "";
}

function applyVariableLabels(items) {
  if (!Array.isArray(items)) {
    return [];
  }
  
  // Fallback mapping for display names if backend doesn't provide them
  const fallbackLabels = {
    "tmp2m": "Surface Temperature",
    "wspd10m": "Wind Speed",
    "precip_rain": "Rain",
    "precip_snow": "Snow",
    "precip_sleet": "Sleet",
    "precip_frzr": "Freezing Rain",
    "radar_rain": "Radar (Rain)",
    "radar_snow": "Radar (Snow)",
    "radar_sleet": "Radar (Sleet)",
    "radar_frzr": "Radar (Freezing Rain)",
  };
  
  return items.map((item) => {
    const id = asId(item);
    if (!id) {
      return item;
    }
    
    // Priority: 1) display_name from item, 2) VARIABLE_LABELS config, 3) fallback, 4) id
    let label = null;
    if (item && typeof item === "object" && item.display_name) {
      label = item.display_name;
    } else if (VARIABLE_LABELS[id]) {
      label = VARIABLE_LABELS[id];
    } else if (fallbackLabels[id]) {
      label = fallbackLabels[id];
    }
    
    if (!label) {
      return item;
    }
    if (item && typeof item === "object") {
      return { ...item, id, label };
    }
    return { id, label };
  });
}

function setSelectOptions(select, items, { includeLatest = false } = {}) {
  if (!select) {
    return;
  }
  select.innerHTML = "";
  const rawValues = includeLatest
    ? ["latest", ...items.filter((item) => asId(item) !== "latest")]
    : items;
  rawValues.forEach((item) => {
    const option = document.createElement("option");
    const idValue = asId(item);
    option.value = idValue;
    option.textContent = asLabel(item) || idValue;
    select.appendChild(option);
  });
}

export function applyFramesToSlider(frames, currentValue) {
  const fhSlider = document.getElementById("fh-slider");
  const fhDisplay = document.getElementById("fh-display");
  if (!fhSlider || !fhDisplay) {
    return;
  }
  const normalized = normalizeFrames(frames);
  if (!normalized.length) {
    fhSlider.min = DEFAULTS.fhStart.toString();
    fhSlider.max = DEFAULTS.fhEnd.toString();
    fhSlider.step = DEFAULTS.fhStep.toString();
    fhSlider.value = DEFAULTS.fhStart.toString();
    fhDisplay.textContent = `FH: ${DEFAULTS.fhStart}`;
    return;
  }
  const min = normalized[0];
  const max = normalized[normalized.length - 1];
  fhSlider.min = min.toString();
  fhSlider.max = max.toString();
  fhSlider.step = DEFAULTS.fhStep.toString();
  const value = Number.isFinite(currentValue) ? currentValue : min;
  fhSlider.value = value.toString();
  fhDisplay.textContent = `FH: ${value}`;
}

export async function initControls({
  onVariableChange,
  onForecastHourChange,
  onPlayToggle,
}) {
  const modelSelect = document.getElementById("model-select");
  const regionSelect = document.getElementById("region-select");
  const runSelect = document.getElementById("run-select");
  const varSelect = document.getElementById("var-select");
  const fhSlider = document.getElementById("fh-slider");
  const fhDisplay = document.getElementById("fh-display");
  const playToggle = document.getElementById("play-toggle");

  let models = [];
  let regions = [];
  let runs = [];
  let variables = [];
  let frames = [];

  let selectedModel = DEFAULTS.model;
  let selectedRegion = DEFAULTS.region;
  let selectedRun = DEFAULTS.run;
  let selectedVar = DEFAULTS.variable;
  let legendMeta = null;

  try {
    models = await fetchJson(`${API_BASE}/models`);
  } catch (error) {
    console.warn("Failed to load models list", error);
  }

  const modelIds = models.map(asId).filter(Boolean);
  if (modelIds.length && !modelIds.includes(selectedModel)) {
    selectedModel = modelIds[0];
  }
  setSelectOptions(modelSelect, models);
  if (modelSelect) {
    modelSelect.value = selectedModel;
  }

  try {
    regions = await fetchJson(`${API_BASE}/${selectedModel}/regions`);
  } catch (error) {
    console.warn("Failed to load regions list", error);
  }

  const regionIds = regions.map(asId).filter(Boolean);
  if (regionIds.length && !regionIds.includes(selectedRegion)) {
    selectedRegion = regionIds[0];
  }
  setSelectOptions(regionSelect, regions);
  if (regionSelect) {
    regionSelect.value = selectedRegion;
  }

  try {
    runs = await fetchJson(`${API_BASE}/${selectedModel}/${selectedRegion}/runs`);
  } catch (error) {
    console.warn("Failed to load runs list", error);
  }
  const runIds = runs.map(asId).filter(Boolean);
  if (runIds.length && !runIds.includes(selectedRun)) {
    selectedRun = runIds[0];
  }
  setSelectOptions(runSelect, runs, { includeLatest: true });
  if (runSelect) {
    runSelect.value = selectedRun;
  }

  try {
    variables = await fetchJson(`${API_BASE}/${selectedModel}/${selectedRegion}/latest/vars`);
  } catch (error) {
    console.warn("Failed to load vars list", error);
    variables = VARIABLES.map((variable) => variable.id);
  }

  variables = applyVariableLabels(variables);

  const varIds = variables.map(asId).filter(Boolean);
  if (varIds.length && !varIds.includes(selectedVar)) {
    selectedVar = varIds[0];
  }
  if (varSelect) {
    setSelectOptions(varSelect, variables);
    varSelect.value = selectedVar;
  }

  try {
    const framesResponse = await fetchJson(
      `${API_BASE}/${selectedModel}/${selectedRegion}/latest/${selectedVar}/frames`
    );
    frames = normalizeFrames(framesResponse);
    if (Array.isArray(framesResponse)) {
      const first = framesResponse.find((row) => row && row.has_cog);
      legendMeta = first?.meta?.meta ?? null;
    }
  } catch (error) {
    console.warn("Failed to load frames list", error);
    frames = [];
  }

  const initialFh = frames.length ? frames[0] : DEFAULTS.fhStart;
  applyFramesToSlider(frames, initialFh);

  if (varSelect) {
    varSelect.addEventListener("change", (event) => {
      const value = event.target.value;
      console.debug("var change", value);
      onVariableChange(value);
    });
  }

  if (fhSlider && fhDisplay) {
    fhSlider.addEventListener("input", (event) => {
      const value = Number(event.target.value);
      fhDisplay.textContent = `FH: ${value}`;
      onForecastHourChange(value);
    });
  }

  if (playToggle) {
    playToggle.addEventListener("click", () => {
      const isPlaying = playToggle.dataset.playing === "true";
      const nextState = !isPlaying;
      playToggle.dataset.playing = nextState ? "true" : "false";
      playToggle.textContent = nextState ? "Pause" : "Play";
      onPlayToggle(nextState);
    });
  }

  return {
    model: selectedModel,
    region: selectedRegion,
    run: selectedRun,
    varKey: selectedVar,
    legendMeta,
    frames,
    models,
    regions,
    runs,
    variables,
  };
}
