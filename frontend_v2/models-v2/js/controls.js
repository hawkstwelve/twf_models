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

function formatLatestLabel(runId) {
  if (!runId) {
    return "Latest";
  }
  const match = String(runId).match(/_(\d{2})z$/i);
  if (!match) {
    return "Latest";
  }
  return `Latest (${match[1]}z)`;
}

function applyVariableLabels(items) {
  if (!Array.isArray(items)) {
    return [];
  }
  
  // Fallback mapping for display names if backend doesn't provide them
  const fallbackLabels = {
    "tmp2m": "Surface Temperature",
    "wspd10m": "Wind Speed",
    "refc": "Composite Reflectivity",
    "precip_rain": "Rain",
    "precip_snow": "Snow",
    "precip_sleet": "Sleet",
    "precip_frzr": "Freezing Rain",
    "radar_ptype": "Composite Reflectivity + P-Type",
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
  let rawValues = items;
  if (includeLatest && items.length > 0) {
    const filtered = items.filter((item) => asId(item) !== "latest");
    const latestItem = filtered[0];
    if (latestItem) {
      const latestLabel = formatLatestLabel(asId(latestItem) || asLabel(latestItem));
      rawValues = [
        { id: "latest", label: latestLabel },
        ...filtered.slice(1),
      ];
    } else {
      rawValues = items;
    }
  }
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
    delete fhSlider.dataset.mode;
    delete fhSlider.dataset.frames;
    fhSlider.min = DEFAULTS.fhStart.toString();
    fhSlider.max = DEFAULTS.fhEnd.toString();
    fhSlider.step = DEFAULTS.fhStep.toString();
    fhSlider.value = DEFAULTS.fhStart.toString();
    fhDisplay.textContent = `FH: ${DEFAULTS.fhStart}`;
    return;
  }
  const selectedFh = pickNearestFh(normalized, Number.isFinite(currentValue) ? currentValue : normalized[0]);
  const selectedIndex = Math.max(0, normalized.indexOf(selectedFh));
  fhSlider.dataset.mode = "index";
  fhSlider.dataset.frames = JSON.stringify(normalized);
  fhSlider.min = "0";
  fhSlider.max = Math.max(0, normalized.length - 1).toString();
  fhSlider.step = "1";
  fhSlider.value = selectedIndex.toString();
  fhDisplay.textContent = `FH: ${selectedFh}`;
}

function pickDefaultValue(items, preferred) {
  const ids = items.map(asId).filter(Boolean);
  if (preferred && ids.includes(preferred)) {
    return preferred;
  }
  return ids[0] ?? preferred ?? "";
}

function pickNearestFh(available, current) {
  if (!Array.isArray(available) || !available.length) {
    return DEFAULTS.fhStart;
  }
  if (Number.isFinite(current) && available.includes(current)) {
    return current;
  }
  if (!Number.isFinite(current)) {
    return available[0];
  }
  return available.reduce((nearest, value) => {
    const nearestDelta = Math.abs(nearest - current);
    const valueDelta = Math.abs(value - current);
    if (valueDelta < nearestDelta) {
      return value;
    }
    return nearest;
  }, available[0]);
}

function getSliderValue() {
  const fhSlider = document.getElementById("fh-slider");
  if (!fhSlider) {
    return null;
  }
  if (fhSlider.dataset.mode === "index") {
    try {
      const frames = JSON.parse(fhSlider.dataset.frames || "[]");
      const index = Number(fhSlider.value);
      if (!Number.isInteger(index) || index < 0 || index >= frames.length) {
        return null;
      }
      const fh = Number(frames[index]);
      return Number.isFinite(fh) ? fh : null;
    } catch (_) {
      return null;
    }
  }
  const value = Number(fhSlider.value);
  return Number.isFinite(value) ? value : null;
}

async function fetchVars({ model, region, run }) {
  const runKey = run && run !== "latest" ? run : "latest";
  try {
    return await fetchJson(`${API_BASE}/${model}/${region}/${runKey}/vars`);
  } catch (error) {
    console.warn("Failed to load vars list", error);
    return VARIABLES.map((variable) => variable.id);
  }
}

async function fetchFrames({ model, region, run, varKey }) {
  const runKey = run && run !== "latest" ? run : "latest";
  try {
    const response = await fetchJson(`${API_BASE}/${model}/${region}/${runKey}/${varKey}/frames`);
    const frames = normalizeFrames(response);
    if (Array.isArray(response)) {
      const first = response.find((row) => row && row.has_cog);
      return { frames, legendMeta: first?.meta?.meta ?? null };
    }
    return { frames, legendMeta: null };
  } catch (error) {
    console.warn("Failed to load frames list", error);
    return { frames: [], legendMeta: null };
  }
}

export async function initControls({
  onSelectionChange,
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
  let currentFh = DEFAULTS.fhStart;
  let pollTimer = null;

  try {
    models = await fetchJson(`${API_BASE}/models`);
  } catch (error) {
    console.warn("Failed to load models list", error);
  }

  const modelIds = models.map(asId).filter(Boolean);
  selectedModel = pickDefaultValue(models, selectedModel);
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
  selectedRegion = pickDefaultValue(regions, selectedRegion);
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
  selectedRun = DEFAULTS.run;
  setSelectOptions(runSelect, runs, { includeLatest: true });
  if (runSelect) {
    runSelect.value = selectedRun;
  }

  variables = await fetchVars({ model: selectedModel, region: selectedRegion, run: selectedRun });

  variables = applyVariableLabels(variables);

  selectedVar = pickDefaultValue(variables, selectedVar);
  if (varSelect) {
    setSelectOptions(varSelect, variables);
    varSelect.value = selectedVar;
  }

  async function notifySelectionChange(extra = {}) {
    if (!onSelectionChange) {
      return;
    }
    onSelectionChange({
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
      ...extra,
    });
  }

  async function updateFrames({ preserveFh, userInitiated }) {
    ({ frames, legendMeta } = await fetchFrames({
      model: selectedModel,
      region: selectedRegion,
      run: selectedRun,
      varKey: selectedVar,
    }));
    const normalized = normalizeFrames(frames);
    const currentValue = getSliderValue();
    const baselineFh = Number.isFinite(currentValue) ? currentValue : currentFh;
    const preferredFh = preserveFh
      ? pickNearestFh(normalized, baselineFh)
      : (normalized[0] ?? DEFAULTS.fhStart);
    currentFh = preferredFh;
    await notifySelectionChange({ preferredFh, userInitiated });
  }

  function stopFramesPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startFramesPolling() {
    stopFramesPolling();
    pollTimer = window.setInterval(() => {
      if (document.hidden) {
        return;
      }
      updateFrames({ preserveFh: true, userInitiated: false });
    }, 30000);
  }

  await updateFrames({ preserveFh: false, userInitiated: false });
  applyFramesToSlider(frames, currentFh);
  startFramesPolling();

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopFramesPolling();
      return;
    }
    updateFrames({ preserveFh: true, userInitiated: false });
    startFramesPolling();
  });

  if (modelSelect) {
    modelSelect.addEventListener("change", async (event) => {
      selectedModel = event.target.value;
      selectedRun = DEFAULTS.run;
      try {
        regions = await fetchJson(`${API_BASE}/${selectedModel}/regions`);
      } catch (error) {
        console.warn("Failed to load regions list", error);
        regions = [];
      }
      selectedRegion = pickDefaultValue(regions, DEFAULTS.region);
      setSelectOptions(regionSelect, regions);
      if (regionSelect) {
        regionSelect.value = selectedRegion;
      }

      try {
        runs = await fetchJson(`${API_BASE}/${selectedModel}/${selectedRegion}/runs`);
      } catch (error) {
        console.warn("Failed to load runs list", error);
        runs = [];
      }
      setSelectOptions(runSelect, runs, { includeLatest: true });
      if (runSelect) {
        runSelect.value = selectedRun;
      }

      variables = await fetchVars({ model: selectedModel, region: selectedRegion, run: selectedRun });
      variables = applyVariableLabels(variables);
      selectedVar = pickDefaultValue(variables, DEFAULTS.variable);
      if (varSelect) {
        setSelectOptions(varSelect, variables);
        varSelect.value = selectedVar;
      }

      await updateFrames({ preserveFh: false, userInitiated: true });
    });
  }

  if (regionSelect) {
    regionSelect.addEventListener("change", async (event) => {
      selectedRegion = event.target.value;
      selectedRun = DEFAULTS.run;
      try {
        runs = await fetchJson(`${API_BASE}/${selectedModel}/${selectedRegion}/runs`);
      } catch (error) {
        console.warn("Failed to load runs list", error);
        runs = [];
      }
      setSelectOptions(runSelect, runs, { includeLatest: true });
      if (runSelect) {
        runSelect.value = selectedRun;
      }

      variables = await fetchVars({ model: selectedModel, region: selectedRegion, run: selectedRun });
      variables = applyVariableLabels(variables);
      selectedVar = pickDefaultValue(variables, DEFAULTS.variable);
      if (varSelect) {
        setSelectOptions(varSelect, variables);
        varSelect.value = selectedVar;
      }

      await updateFrames({ preserveFh: false, userInitiated: true });
    });
  }

  if (runSelect) {
    runSelect.addEventListener("change", async (event) => {
      selectedRun = event.target.value || DEFAULTS.run;
      variables = await fetchVars({ model: selectedModel, region: selectedRegion, run: selectedRun });
      variables = applyVariableLabels(variables);
      selectedVar = pickDefaultValue(variables, DEFAULTS.variable);
      if (varSelect) {
        setSelectOptions(varSelect, variables);
        varSelect.value = selectedVar;
      }

      await updateFrames({ preserveFh: false, userInitiated: true });
    });
  }

  if (varSelect) {
    varSelect.addEventListener("change", async (event) => {
      selectedVar = event.target.value;
      await updateFrames({ preserveFh: false, userInitiated: true });
    });
  }

  if (fhSlider && fhDisplay) {
    fhSlider.addEventListener("input", (event) => {
      let nextFh = Number(event.target.value);
      if (fhSlider.dataset.mode === "index") {
        try {
          const frames = JSON.parse(fhSlider.dataset.frames || "[]");
          const index = Number(event.target.value);
          if (Number.isInteger(index) && index >= 0 && index < frames.length) {
            nextFh = Number(frames[index]);
          }
        } catch (_) {
          nextFh = Number(event.target.value);
        }
      }
      if (!Number.isFinite(nextFh)) {
        return;
      }
      fhDisplay.textContent = `FH: ${nextFh}`;
      currentFh = nextFh;
      onForecastHourChange(nextFh);
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
    preferredFh: currentFh,
    userInitiated: false,
    models,
    regions,
    runs,
    variables,
  };
}
