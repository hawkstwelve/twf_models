import { API_BASE_URL, absolutizeUrl } from "@/lib/config";
import type { LegacyFrameRow } from "@/lib/api";

function rewriteFrontendOriginToApiOrigin(url: string): string {
  try {
    const resolved = new URL(url);
    const apiOrigin = new URL(API_BASE_URL).origin;
    const frontendOrigin = window.location.origin;
    if (resolved.origin === frontendOrigin && resolved.origin !== apiOrigin) {
      const rewritten = `${apiOrigin}${resolved.pathname}${resolved.search}${resolved.hash}`;
      console.warn("[offline] Rewriting frame URL from frontend origin to API origin", {
        from: url,
        to: rewritten,
      });
      return rewritten;
    }
  } catch {
    // fall through to original url
  }
  return url;
}

function stripPmtilesProtocol(pathOrUrl: string): string {
  return pathOrUrl.startsWith("pmtiles://") ? pathOrUrl.slice("pmtiles://".length) : pathOrUrl;
}

export function toAbsoluteUrl(pathOrUrl: string): string {
  return absolutizeUrl(pathOrUrl);
}

export function toPmtilesProtocolUrl(pathOrUrl: string): string {
  const absoluteUrl = toAbsoluteUrl(stripPmtilesProtocol(pathOrUrl));
  return `pmtiles://${absoluteUrl}`;
}

export function buildLegacyFallbackTileUrl(params: {
  model: string;
  region: string;
  run: string;
  varKey: string;
  fh: number;
}): string {
  const enc = encodeURIComponent;
  return absolutizeUrl(
    `/tiles/v2/${enc(params.model)}/${enc(params.region)}/${enc(params.run)}/${enc(params.varKey)}/${enc(params.fh)}/{z}/{x}/{y}.png`
  );
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
  const fallback = `/tiles/${params.model}/${params.run}/${params.varKey}/${params.frameId}.pmtiles`;
  const candidateUrl = params.frameUrl && params.frameUrl.trim() ? params.frameUrl.trim() : fallback;
  const absoluteUrl = toAbsoluteUrl(stripPmtilesProtocol(candidateUrl));
  const rewrittenUrl = rewriteFrontendOriginToApiOrigin(absoluteUrl);
  return toPmtilesProtocolUrl(rewrittenUrl);
}
