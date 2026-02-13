import { API_BASE_URL, absolutizeUrl } from "@/lib/config";

function rewriteFrontendOriginToApiOrigin(url: string): string {
  try {
    const resolved = new URL(url);
    const apiOrigin = new URL(API_BASE_URL).origin;
    const frontendOrigin = window.location.origin;
    if (resolved.origin === frontendOrigin && resolved.origin !== apiOrigin) {
      return `${apiOrigin}${resolved.pathname}${resolved.search}${resolved.hash}`;
    }
  } catch {
    // Keep original URL if parsing fails.
  }
  return url;
}

function normalizedForecastHour(value?: number | string): string {
  if (value === undefined || value === null) {
    return "";
  }
  const asNumber = Number(value);
  if (Number.isFinite(asNumber) && asNumber >= 0) {
    return String(Math.trunc(asNumber));
  }
  return String(value).trim();
}

export function buildOfflineFrameImageUrl(params: {
  model: string;
  run: string;
  varKey: string;
  fh?: number | string;
  frameImageUrl?: string | null;
  extension?: "webp" | "png";
}): string {
  const frameToken = normalizedForecastHour(params.fh) || "0";
  const extension = params.extension ?? "webp";
  const fallback = `/frames/${params.model}/${params.run}/${params.varKey}/${frameToken}.${extension}`;
  const candidate = params.frameImageUrl?.trim() ? params.frameImageUrl.trim() : fallback;
  const absoluteUrl = absolutizeUrl(candidate);
  return rewriteFrontendOriginToApiOrigin(absoluteUrl);
}
