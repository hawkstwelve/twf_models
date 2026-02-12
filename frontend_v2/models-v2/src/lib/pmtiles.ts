import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";

const PMTILES_PROTOCOL_KEY = "__twf_pmtiles_protocol_installed__";

export function ensurePmtilesProtocol(): void {
  const globalWindow = window as Window & { [PMTILES_PROTOCOL_KEY]?: boolean };
  if (globalWindow[PMTILES_PROTOCOL_KEY]) {
    return;
  }

  const protocol = new Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  globalWindow[PMTILES_PROTOCOL_KEY] = true;
}
