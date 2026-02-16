// ---------------------------------------------------------------------------
// Feature-flag helpers — persisted in localStorage, overridable via URL params
// ---------------------------------------------------------------------------

const LEGACY_TILES_KEY = "twf_use_legacy_tiles";

/**
 * Read the `?legacy=1` query-param override on first call and persist it to
 * localStorage so the session "sticks" even after the query param is removed.
 */
function applyUrlOverride(): void {
  try {
    const params = new URLSearchParams(window.location.search);
    const legacyParam = params.get("legacy");
    if (legacyParam === "1" || legacyParam === "0") {
      localStorage.setItem(LEGACY_TILES_KEY, legacyParam);
    }
  } catch {
    // URL parsing or localStorage may be unavailable.
  }
}

// Run once at module load time.
applyUrlOverride();

export function getUseLegacyTiles(): boolean {
  try {
    return localStorage.getItem(LEGACY_TILES_KEY) === "1";
  } catch {
    return false;
  }
}

export function setUseLegacyTiles(enabled: boolean): void {
  try {
    localStorage.setItem(LEGACY_TILES_KEY, enabled ? "1" : "0");
  } catch {
    // localStorage may be unavailable.
  }
}

// Log once on init so developers can quickly see the active mode.
console.info(`Legacy tiles: ${getUseLegacyTiles() ? "ON" : "OFF"}`);
