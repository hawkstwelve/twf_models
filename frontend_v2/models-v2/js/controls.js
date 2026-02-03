import { DEFAULTS, VARIABLES } from "./config.js";

export function initControls({
  onVariableChange,
  onForecastHourChange,
  onPlayToggle,
}) {
  const varSelect = document.getElementById("var-select");
  const fhSlider = document.getElementById("fh-slider");
  const fhDisplay = document.getElementById("fh-display");
  const playToggle = document.getElementById("play-toggle");

  VARIABLES.forEach((variable) => {
    const option = document.createElement("option");
    option.value = variable.id;
    option.textContent = variable.label;
    varSelect.appendChild(option);
  });

  varSelect.value = DEFAULTS.variable;
  fhSlider.min = DEFAULTS.fhStart.toString();
  fhSlider.max = DEFAULTS.fhEnd.toString();
  fhSlider.step = DEFAULTS.fhStep.toString();
  fhSlider.value = DEFAULTS.fhStart.toString();
  fhDisplay.textContent = `FH: ${DEFAULTS.fhStart}`;

  varSelect.addEventListener("change", (event) => {
    onVariableChange(event.target.value);
  });

  fhSlider.addEventListener("input", (event) => {
    const value = Number(event.target.value);
    fhDisplay.textContent = `FH: ${value}`;
    onForecastHourChange(value);
  });

  playToggle.addEventListener("click", () => {
    const isPlaying = playToggle.dataset.playing === "true";
    const nextState = !isPlaying;
    playToggle.dataset.playing = nextState ? "true" : "false";
    playToggle.textContent = nextState ? "Pause" : "Play";
    onPlayToggle(nextState);
  });
}
