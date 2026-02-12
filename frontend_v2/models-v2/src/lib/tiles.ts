import { TILES_BASE } from "@/lib/config";
import type { LegacyFrameRow } from "@/lib/api";

function baseRoot() {
  return TILES_BASE.replace(/\/?(api\/v2|api|tiles\/v2)\/?$/i, "");
}

export function toAbsoluteUrl(pathOrUrl: string): string {
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
    return pathOrUrl;
  }
  const root = baseRoot().replace(/\/$/, "");
  const path = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${root}${path}`;
}

export function toPmtilesProtocolUrl(pathOrUrl: string): string {
  if (pathOrUrl.startsWith("pmtiles://")) {
    return pathOrUrl;
  }
  return `pmtiles://${toAbsoluteUrl(pathOrUrl)}`;
}

export function buildLegacyFallbackTileUrl(params: {
  model: string;
  region: string;
  run: string;
  varKey: string;
  fh: number;
}): string {
  const root = baseRoot().replace(/\/$/, "");
  const enc = encodeURIComponent;
  return `${root}/tiles/v2/${enc(params.model)}/${enc(params.region)}/${enc(params.run)}/${enc(params.varKey)}/${enc(params.fh)}/{z}/{x}/{y}.png`;
}

export function buildLegacyTileUrlFromFrame(params: {
  model: string;
  region: string;
  run: string;
  varKey: string;
  fh: number;
  frameRow?: LegacyFrameRow | null;
}): string {
  if (params.frameRow?.tile_url_template) {
    return toAbsoluteUrl(params.frameRow.tile_url_template);
  }
  return buildLegacyFallbackTileUrl(params);
}

export function buildOfflinePmtilesUrl(params: {
  model: string;
  run: string;
  varKey: string;
  frameId: string;
  frameUrl?: string | null;
}): string {
  if (params.frameUrl && params.frameUrl.trim()) {
    return toPmtilesProtocolUrl(params.frameUrl);
  }
  const fallback = `/tiles/${params.model}/${params.run}/${params.varKey}/${params.frameId}.pmtiles`;
  return toPmtilesProtocolUrl(fallback);
}
