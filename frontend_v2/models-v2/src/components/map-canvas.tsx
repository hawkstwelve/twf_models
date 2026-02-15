import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type StyleSpecification } from "maplibre-gl";

import { DEFAULTS } from "@/lib/config";

const BASEMAP_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors ' +
  '&copy; <a href="https://carto.com/attributions">CARTO</a>';

const CARTO_LIGHT_BASE_TILES = [
  "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
  "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
  "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
  "https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
];

const CARTO_LIGHT_LABEL_TILES = [
  "https://a.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
  "https://b.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
  "https://c.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
  "https://d.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
];

const REGION_VIEWS: Record<string, { center: [number, number]; zoom: number }> = {
  pnw: { center: [-120.8, 45.6], zoom: 6 },
  published: { center: [-120.8, 45.6], zoom: 6 },
};

const REGION_BOUNDS: Record<string, [number, number, number, number]> = {
  pnw: [-125.5, 41.5, -111.0, 49.5],
  published: [-125.5, 41.5, -111.0, 49.5],
};

const HIDDEN_OPACITY = 0;
const DEFAULT_OVERLAY_OPACITY = 0.85;
const OVERLAY_CANVAS_WIDTH = 2048;
const OVERLAY_CANVAS_HEIGHT = 2046;
const CROSSFADE_DURATION_MS = 120;
const PREFETCH_CONCURRENCY = 4;
const PREFETCH_NEARBY_FRAMES = 24;

/**
 * Byte-budgeted bitmap cache.
 * Each decoded RGBA bitmap costs w * h * 4 bytes.
 * Desktop budget ~800 MB, mobile ~300 MB.
 */
const IS_MOBILE =
  typeof navigator !== "undefined" &&
  (navigator.maxTouchPoints > 0 || /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent));
const BITMAP_CACHE_BUDGET_BYTES = IS_MOBILE ? 300 * 1024 * 1024 : 800 * 1024 * 1024;

function estimateBitmapBytes(frame: DecodedFrame): number {
  const w = (frame as { width?: number }).width ?? OVERLAY_CANVAS_WIDTH;
  const h = (frame as { height?: number }).height ?? OVERLAY_CANVAS_HEIGHT;
  return w * h * 4;
}

const IMG_SOURCE_ID = "twf-canvas-overlay";
const IMG_LAYER_ID = "twf-img-overlay";

type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];
type DecodedFrame = ImageBitmap | HTMLImageElement;

type MutableCanvasSource = maplibregl.CanvasSource & {
  setCoordinates?: (coordinates: ImageCoordinates) => void;
  play?: () => void;
};

type DecodeWorkerRequest = {
  id: number;
  url: string;
  cacheMode: RequestCache;
};

type DecodeWorkerSuccess = {
  id: number;
  url: string;
  bitmap: ImageBitmap;
};

type DecodeWorkerFailure = {
  id: number;
  url: string;
  error: string;
};

type DecodeWorkerResponse = DecodeWorkerSuccess | DecodeWorkerFailure;

type PendingDecodeRequest = {
  id: number;
  url: string;
  resolve: (bitmap: ImageBitmap) => void;
  reject: (error: Error) => void;
  timeoutId: number;
};

function getResamplingMode(variable?: string): "nearest" | "linear" {
  // Categorical fields must use nearest-neighbor to avoid interpolating
  // between discrete ptype/reflectivity bins.
  if (variable && (variable.includes("radar") || variable.includes("ptype"))) {
    return "nearest";
  }
  // Continuous fields (tmp2m, wspd10m, qpf6h, etc.) benefit from bilinear
  // filtering — smoother gradients and no visible pixel edges.
  return "linear";
}

function imageCoordinatesForRegion(region?: string): ImageCoordinates {
  const [west, south, east, north] = (region && REGION_BOUNDS[region]) || REGION_BOUNDS.pnw;
  return [
    [west, north],
    [east, north],
    [east, south],
    [west, south],
  ];
}

function canvasSourceFor(canvas: HTMLCanvasElement, coordinates: ImageCoordinates) {
  return {
    type: "canvas" as const,
    canvas,
    coordinates,
    animate: true,
  };
}

/**
 * Atomically blit a fully-composited source canvas onto the display canvas
 * that MapLibre reads from.  A single "copy" drawImage ensures the GPU
 * texture is never sampled between two sequential draw calls.
 */
function blitToDisplay(display: HTMLCanvasElement, source: HTMLCanvasElement): void {
  const ctx = display.getContext("2d");
  if (!ctx) return;
  ctx.globalCompositeOperation = "copy";
  ctx.drawImage(source, 0, 0);
  ctx.globalCompositeOperation = "source-over";
}

function drawFrameToCanvas(
  canvas: HTMLCanvasElement,
  frontFrame: CanvasImageSource | null,
  backFrame: CanvasImageSource | null,
  progress: number,
  displayCanvas?: HTMLCanvasElement | null
): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("2D canvas context unavailable for overlay draw");
  }
  const w = canvas.width;
  const h = canvas.height;
  const clampedProgress = Math.min(1, Math.max(0, progress));

  // --- Reset all sticky canvas state ---
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
  ctx.imageSmoothingEnabled = canvas.dataset.resamplingMode !== "nearest";

  // Guard against closed ImageBitmaps (evicted from cache while still referenced)
  const safeDraw = (img: CanvasImageSource, composite: GlobalCompositeOperation) => {
    try {
      ctx.globalCompositeOperation = composite;
      ctx.drawImage(img, 0, 0, w, h);
    } catch {
      // ImageBitmap was closed — skip this frame silently.
    }
  };

  const hasFront = Boolean(frontFrame);
  const hasBack = Boolean(backFrame);

  if (!hasFront && !hasBack) {
    // Nothing to draw — clear canvas so overlay is fully transparent
    // (basemap shows through).
    ctx.globalCompositeOperation = "copy";
    ctx.clearRect(0, 0, w, h);
    return;
  }

  if (hasFront && hasBack && clampedProgress < 1) {
    // Crossfade: draw front at full alpha with "copy" so the canvas always
    // holds fully-opaque pixels (no alpha dip that lets the white basemap
    // bleed through). Then composite the incoming frame on top at the
    // crossfade progress alpha — it smoothly fades in without any
    // intermediate transparency.
    ctx.globalAlpha = 1;
    safeDraw(frontFrame as CanvasImageSource, "copy");
    ctx.globalAlpha = clampedProgress;
    safeDraw(backFrame as CanvasImageSource, "source-over");
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    return;
  }

  // Single frame (or crossfade complete): draw at full alpha using "copy"
  // to atomically replace all canvas contents — transparent source pixels
  // stay transparent (basemap shows through), no flash.
  ctx.globalAlpha = 1;
  if (hasBack) {
    safeDraw(backFrame as CanvasImageSource, "copy");
  } else {
    safeDraw(frontFrame as CanvasImageSource, "copy");
  }
  ctx.globalCompositeOperation = "source-over";

  // Double-buffer: if a separate display canvas was provided, atomically
  // blit the fully-composited result so MapLibre never reads a half-drawn
  // intermediate state.
  if (displayCanvas && displayCanvas !== canvas) {
    blitToDisplay(displayCanvas, canvas);
  }
}

function sampleCenterAlpha(canvas: HTMLCanvasElement | null): number {
  if (!canvas) {
    return 0;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return 0;
  }
  const cx = Math.max(1, Math.floor(canvas.width / 2));
  const cy = Math.max(1, Math.floor(canvas.height / 2));
  try {
    const data = ctx.getImageData(cx - 1, cy - 1, 3, 3).data;
    let sum = 0;
    let count = 0;
    for (let i = 3; i < data.length; i += 4) {
      sum += data[i];
      count += 1;
    }
    return count > 0 ? sum / count : 0;
  } catch {
    return 0;
  }
}

function isCanvasNonBlank(canvas: HTMLCanvasElement | null): boolean {
  if (!canvas) {
    return false;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return false;
  }

  const points: Array<[number, number]> = [];
  const fractions = [0.1, 0.3, 0.5, 0.7, 0.9];
  for (const fy of fractions) {
    for (const fx of fractions) {
      points.push([Math.floor(canvas.width * fx), Math.floor(canvas.height * fy)]);
    }
  }

  try {
    for (const [xRaw, yRaw] of points) {
      const x = Math.min(Math.max(0, xRaw), Math.max(0, canvas.width - 1));
      const y = Math.min(Math.max(0, yRaw), Math.max(0, canvas.height - 1));
      const data = ctx.getImageData(x, y, 1, 1).data;
      if (data[3] > 0 || data[0] !== 0 || data[1] !== 0 || data[2] !== 0) {
        return true;
      }
    }
  } catch {
    return false;
  }

  return false;
}

function setCanvasSourceCoordinates(
  map: maplibregl.Map,
  sourceId: string,
  canvas: HTMLCanvasElement,
  coordinates: ImageCoordinates
): boolean {
  try {
    const source = map.getSource(sourceId) as MutableCanvasSource | undefined;
    if (source && typeof source.setCoordinates === "function") {
      source.setCoordinates(coordinates);
      return true;
    }
  } catch {
    // Source lookup can throw during style teardown.
  }
  return false;
}

function isMapStyleReady(map: maplibregl.Map | null | undefined): map is maplibregl.Map {
  if (!map) {
    return false;
  }
  try {
    return map.isStyleLoaded() === true;
  } catch {
    return false;
  }
}

function hasSource(map: maplibregl.Map, sourceId: string): boolean {
  try {
    return Boolean(map.getSource(sourceId));
  } catch {
    return false;
  }
}

function hasLayer(map: maplibregl.Map, layerId: string): boolean {
  try {
    return Boolean(map.getLayer(layerId));
  } catch {
    return false;
  }
}

function setLayerVisibility(map: maplibregl.Map, id: string, visible: boolean): void {
  if (!isMapStyleReady(map)) {
    return;
  }
  if (!map.getLayer(id)) {
    return;
  }
  try {
    map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  } catch {
    // Style/source may have been torn down mid-frame.
  }
}

function styleFor(): StyleSpecification {
  return {
    version: 8,
    sources: {
      "twf-basemap": {
        type: "raster",
        tiles: CARTO_LIGHT_BASE_TILES,
        tileSize: 256,
        attribution: BASEMAP_ATTRIBUTION,
      },
      "twf-labels": {
        type: "raster",
        tiles: CARTO_LIGHT_LABEL_TILES,
        tileSize: 256,
      },
    } as StyleSpecification["sources"],
    layers: [
      {
        id: "twf-basemap",
        type: "raster" as const,
        source: "twf-basemap",
      },
      {
        id: "twf-labels",
        type: "raster" as const,
        source: "twf-labels",
      },
    ],
  };
}

type MapCanvasProps = {
  frameImageUrl?: string;
  region: string;
  opacity: number;
  variable?: string;
  model?: string;
  prefetchFrameImageUrls?: string[];
  crossfade?: boolean;
  crossfadeDurationMs?: number;
  /** When true the user is actively scrubbing the slider — crossfade is
   *  disabled so frames swap instantly without lingering transitions. */
  isScrubbing?: boolean;
  isFrameReadyRef?: React.MutableRefObject<((url: string) => boolean) | null>;
  /** Direct frame-promotion handle.  Lets the playback loop bypass React
   *  state entirely — sets pendingFrameUrl and triggers a repaint so the
   *  RAF tick picks it up on the very next animation frame. */
  promoteFrameRef?: React.MutableRefObject<((url: string) => void) | null>;
  onFrameImageReady?: (imageUrl: string) => void;
  onFrameImageError?: (imageUrl: string) => void;
  onZoomHint?: (show: boolean) => void;
  onRequestUrl?: (url: string) => void;
};

export function MapCanvas({
  frameImageUrl,
  region,
  opacity,
  variable,
  model,
  prefetchFrameImageUrls = [],
  crossfade = true,
  crossfadeDurationMs = CROSSFADE_DURATION_MS,
  isScrubbing = false,
  isFrameReadyRef,
  promoteFrameRef,
  onFrameImageReady,
  onFrameImageError,
  onZoomHint,
  onRequestUrl,
}: MapCanvasProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const mapDestroyedRef = useRef(false);
  const overlayReadyRef = useRef(false);
  const [isLoaded, setIsLoaded] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);

  const onRequestUrlRef = useRef(onRequestUrl);
  const activeImageUrlRef = useRef<string>("");
  const frontFrameUrlRef = useRef<string>("");
  const frontFrameRef = useRef<DecodedFrame | null>(null);
  const backFrameRef = useRef<DecodedFrame | null>(null);
  const renderTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);
  const bitmapCacheRef = useRef<Map<string, DecodedFrame>>(new Map());
  const bitmapCacheOrderRef = useRef<string[]>([]);
  const cacheBytesRef = useRef(0);
  const cacheHitsRef = useRef(0);
  const cacheMissesRef = useRef(0);

  // Expose cache-hit check so the playback loop can gate on frame readiness
  useEffect(() => {
    if (isFrameReadyRef) {
      isFrameReadyRef.current = (url: string) => bitmapCacheRef.current.has(url);
    }
    return () => {
      if (isFrameReadyRef) {
        isFrameReadyRef.current = null;
      }
    };
  }, [isFrameReadyRef]);

  // Expose direct frame-promotion handle so the playback loop in App.tsx
  // can push a URL straight into pendingFrameUrlRef without waiting for a
  // React state → prop → useEffect round-trip.
  useEffect(() => {
    if (promoteFrameRef) {
      promoteFrameRef.current = (url: string) => {
        if (!url || pendingFrameUrlRef.current === url || frontFrameUrlRef.current === url) {
          return;
        }
        pendingFrameUrlRef.current = url;
        const map = mapRef.current;
        if (map && !mapDestroyedRef.current) {
          try {
            map.triggerRepaint();
          } catch {
            // Map may have been torn down.
          }
        }
      };
    }
    return () => {
      if (promoteFrameRef) {
        promoteFrameRef.current = null;
      }
    };
  }, [promoteFrameRef]);
  const pendingFrameUrlRef = useRef<string>("");
  const lastDrawnFrameUrlRef = useRef<string>("");
  const lastDrawTimestampRef = useRef<number>(0);
  const opacityRef = useRef(opacity);
  const resamplingModeRef = useRef<"nearest" | "linear">("nearest");
  const runVarTokenRef = useRef(0);
  const currentFrameIndexRef = useRef<number>(-1);
  const currentFrameUrlRef = useRef<string>("");
  const firstDrawLoggedTokenRef = useRef<number>(-1);
  const firstFramePromotedTokenRef = useRef<number>(-1);
  const firstFramePromotedRef = useRef(false);
  const rafStartedRef = useRef(false);
  const pendingPromotionRef = useRef<{
    url: string;
    requestedAt: number;
  } | null>(null);
  const lastPromoteTimestampRef = useRef<number>(0);
  const frameFailureCountsRef = useRef<Map<string, number>>(new Map());
  const frameRetryTimerRef = useRef<number | null>(null);
  const fadeRef = useRef<{
    startedAt: number;
    durationMs: number;
    targetUrl: string;
  } | null>(null);
  const animationRafRef = useRef<number | null>(null);
  const decodeWorkerRef = useRef<Worker | null>(null);
  const decodeWorkerHealthyRef = useRef(true);
  const decodeRequestSeqRef = useRef(0);
  const decodeRequestsRef = useRef<Map<number, PendingDecodeRequest>>(new Map());
  const inFlightDecodeByUrlRef = useRef<Map<string, Promise<DecodedFrame>>>(new Map());

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const compositeCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);

  useEffect(() => {
    onRequestUrlRef.current = onRequestUrl;
  }, [onRequestUrl]);

  const view = useMemo(() => {
    return REGION_VIEWS[region] ?? {
      center: [DEFAULTS.center[1], DEFAULTS.center[0]] as [number, number],
      zoom: DEFAULTS.zoom,
    };
  }, [region]);

  const overlayMinZoom = useMemo(() => (model === "gfs" ? 6 : 3), [model]);
  const resamplingMode = useMemo(() => getResamplingMode(variable), [variable]);
  const imageCoordinates = useMemo(() => imageCoordinatesForRegion(region), [region]);

  const canMutateMap = useCallback((map: maplibregl.Map | null | undefined): map is maplibregl.Map => {
    return Boolean(map && !mapDestroyedRef.current && mapRef.current === map && isMapStyleReady(map));
  }, []);

  const enforceOverlayState = useCallback(
    (targetOpacity: number, { force = false }: { force?: boolean } = {}) => {
      // During an active crossfade, skip raster-opacity / visibility
      // changes — they cause MapLibre to schedule an internal re-render
      // that can briefly glitch the canvas source texture.  The RAF tick
      // calls enforceOverlayState with { force: true } once the fade
      // completes or is canceled.
      if (!force && fadeRef.current) {
        return;
      }

      const map = mapRef.current;
      if (!map || !canMutateMap(map) || !overlayReadyRef.current) {
        return;
      }

      if (!map.getLayer(IMG_LAYER_ID)) {
        return;
      }

      try {
        const hasRenderableFrame = Boolean(frontFrameRef.current || backFrameRef.current || pendingFrameUrlRef.current);
        setLayerVisibility(map, IMG_LAYER_ID, hasRenderableFrame);
        if (hasRenderableFrame) {
          const effectiveOpacity = targetOpacity > 0 ? targetOpacity : DEFAULT_OVERLAY_OPACITY;
          map.setPaintProperty(IMG_LAYER_ID, "raster-opacity", effectiveOpacity);
        }
      } catch {
        // Style/source may have been torn down mid-frame.
      }
    },
    [canMutateMap]
  );

  const removeBitmapFromCache = useCallback((url: string) => {
    const cached = bitmapCacheRef.current.get(url);
    if (cached) {
      cacheBytesRef.current = Math.max(0, cacheBytesRef.current - estimateBitmapBytes(cached));
      // Only close the ImageBitmap if it's NOT currently being displayed.
      // frontFrameRef / backFrameRef hold direct references to the same object;
      // closing it while in use causes DOMException in drawImage.
      const isActiveFrame =
        cached === frontFrameRef.current || cached === backFrameRef.current;
      if (!isActiveFrame) {
        try {
          if (cached instanceof ImageBitmap) {
            cached.close();
          }
        } catch {
          // noop
        }
      }
      bitmapCacheRef.current.delete(url);
    }
    bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== url);
  }, []);

  const decodeWithImageElement = useCallback((url: string): Promise<HTMLImageElement> => {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.decoding = "async";
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(`Failed to decode image element for ${url}`));
      img.src = url;
    });
  }, []);

  const resolveRequestCacheMode = useCallback((url: string): RequestCache => {
    let cacheMode: RequestCache = "default";
    try {
      const parsed = new URL(url, window.location.origin);
      if (parsed.searchParams.has("v")) {
        cacheMode = "force-cache";
      }
    } catch {
      cacheMode = "default";
    }
    return cacheMode;
  }, []);

  const rejectAllDecodeRequests = useCallback((reason: string) => {
    for (const [, pending] of decodeRequestsRef.current) {
      window.clearTimeout(pending.timeoutId);
      pending.reject(new Error(reason));
    }
    decodeRequestsRef.current.clear();
  }, []);

  const decodeMainThread = useCallback(async (url: string, cacheMode: RequestCache): Promise<DecodedFrame> => {
    if (typeof createImageBitmap === "function") {
      const response = await fetch(url, { mode: "cors", credentials: "omit", cache: cacheMode });
      if (!response.ok) {
        throw new Error(`Failed to fetch overlay bitmap (${response.status} ${response.statusText}) for ${url}`);
      }
      const blob = await response.blob();
      return createImageBitmap(blob);
    }
    return decodeWithImageElement(url);
  }, [decodeWithImageElement]);

  const ensureDecodeWorker = useCallback((): Worker | null => {
    if (decodeWorkerRef.current) {
      return decodeWorkerRef.current;
    }
    if (!decodeWorkerHealthyRef.current) {
      return null;
    }
    if (typeof Worker === "undefined") {
      return null;
    }
    try {
      const worker = new Worker(new URL("../workers/overlayDecode.worker.ts", import.meta.url), { type: "module" });
      worker.onmessage = (event: MessageEvent<DecodeWorkerResponse>) => {
        const payload = event.data;
        const requestId = Number(payload?.id);
        if (!Number.isFinite(requestId)) {
          return;
        }
        const pending = decodeRequestsRef.current.get(requestId);
        if (!pending) {
          return;
        }
        decodeRequestsRef.current.delete(requestId);
        window.clearTimeout(pending.timeoutId);

        if ("bitmap" in payload && payload.bitmap instanceof ImageBitmap) {
          pending.resolve(payload.bitmap);
          return;
        }

        const message = "error" in payload && payload.error ? payload.error : `Overlay decode failed for ${pending.url}`;
        pending.reject(new Error(message));
      };
      worker.onerror = () => {
        decodeWorkerHealthyRef.current = false;
        try {
          worker.terminate();
        } catch {
          // noop
        }
        decodeWorkerRef.current = null;
        rejectAllDecodeRequests("Overlay decode worker crashed");
      };
      decodeWorkerRef.current = worker;
      return worker;
    } catch {
      decodeWorkerHealthyRef.current = false;
      return null;
    }
  }, [rejectAllDecodeRequests]);

  const decodeInWorker = useCallback(
    (url: string, cacheMode: RequestCache): Promise<ImageBitmap> => {
      const worker = ensureDecodeWorker();
      if (!worker) {
        return Promise.reject(new Error("Overlay decode worker unavailable"));
      }
      return new Promise<ImageBitmap>((resolve, reject) => {
        const id = ++decodeRequestSeqRef.current;
        const timeoutId = window.setTimeout(() => {
          const pending = decodeRequestsRef.current.get(id);
          if (!pending) {
            return;
          }
          decodeRequestsRef.current.delete(id);
          reject(new Error(`Overlay decode worker timed out for ${url}`));
        }, 30_000);

        decodeRequestsRef.current.set(id, {
          id,
          url,
          resolve,
          reject,
          timeoutId,
        });

        const message: DecodeWorkerRequest = { id, url, cacheMode };
        worker.postMessage(message);
      });
    },
    [ensureDecodeWorker]
  );

  const fetchBitmap = useCallback(async (url: string): Promise<DecodedFrame> => {
    const cached = bitmapCacheRef.current.get(url);
    if (cached) {
      cacheHitsRef.current += 1;
      bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== url);
      bitmapCacheOrderRef.current.push(url);
      return cached;
    }

    const inFlight = inFlightDecodeByUrlRef.current.get(url);
    if (inFlight) {
      return inFlight;
    }

    cacheMissesRef.current += 1;

    const decodePromise = (async (): Promise<DecodedFrame> => {
      const cacheMode = resolveRequestCacheMode(url);

      let decoded: DecodedFrame;
      if (typeof createImageBitmap === "function") {
        try {
          decoded = await decodeInWorker(url, cacheMode);
        } catch {
          decoded = await decodeMainThread(url, cacheMode);
        }
      } else {
        decoded = await decodeMainThread(url, cacheMode);
      }

      const decodedBytes = estimateBitmapBytes(decoded);
      bitmapCacheRef.current.set(url, decoded);
      bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== url);
      bitmapCacheOrderRef.current.push(url);
      cacheBytesRef.current += decodedBytes;

      // Evict oldest entries to stay within byte budget, but never evict
      // the frame currently being displayed or pending promotion.
      const protectedUrls = new Set<string>();
      if (frontFrameUrlRef.current) protectedUrls.add(frontFrameUrlRef.current);
      if (pendingFrameUrlRef.current) protectedUrls.add(pendingFrameUrlRef.current);

      while (cacheBytesRef.current > BITMAP_CACHE_BUDGET_BYTES && bitmapCacheOrderRef.current.length > 1) {
        // Find the first evictable (non-protected) entry
        const evictIdx = bitmapCacheOrderRef.current.findIndex((u) => !protectedUrls.has(u));
        if (evictIdx < 0) break;
        const evictedUrl = bitmapCacheOrderRef.current.splice(evictIdx, 1)[0];
        if (!evictedUrl) break;
        removeBitmapFromCache(evictedUrl);
      }

      return decoded;
    })();

    inFlightDecodeByUrlRef.current.set(url, decodePromise);

    try {
      return await decodePromise;
    } finally {
      inFlightDecodeByUrlRef.current.delete(url);
    }
  }, [decodeInWorker, decodeMainThread, removeBitmapFromCache, resolveRequestCacheMode]);

  const playCanvasSources = useCallback((map: maplibregl.Map) => {
    const source = map.getSource(IMG_SOURCE_ID) as MutableCanvasSource | undefined;
    source?.play?.();
  }, []);

  const hideImageLayers = useCallback(
    (map: maplibregl.Map) => {
      if (
        !overlayReadyRef.current ||
        !isMapStyleReady(map) ||
        !hasSource(map, IMG_SOURCE_ID) ||
        !hasLayer(map, IMG_LAYER_ID)
      ) {
        return;
      }
      setLayerVisibility(map, IMG_LAYER_ID, false);
    },
    []
  );

  const ensureOverlayInitialized = useCallback(
    (
      map: maplibregl.Map,
      coords: ImageCoordinates,
      targetOpacity: number,
      resampling: "nearest" | "linear",
      minZoom: number
    ): boolean => {
      if (!canMutateMap(map)) {
        return false;
      }

      const hasOverlaySource = hasSource(map, IMG_SOURCE_ID);
      const hasOverlayLayer = hasLayer(map, IMG_LAYER_ID);
      const overlayPresent = hasOverlaySource && hasOverlayLayer;

      if (overlayReadyRef.current && overlayPresent) {
        const canvas = canvasRef.current;
        if (!canvas) {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
        setCanvasSourceCoordinates(map, IMG_SOURCE_ID, canvas, coords);
        try {
          map.setPaintProperty(IMG_LAYER_ID, "raster-resampling", resampling);
          map.setPaintProperty(IMG_LAYER_ID, "raster-fade-duration", 0);
          map.setLayerZoomRange(IMG_LAYER_ID, minZoom, 24);
        } catch {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
        (window as any).__twfOverlayReady = true;
        enforceOverlayState(targetOpacity);
        return true;
      }

      if (!hasOverlaySource) {
        const canvas = canvasRef.current;
        if (!canvas) {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
        try {
          map.addSource(IMG_SOURCE_ID, canvasSourceFor(canvas, coords));
        } catch {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
      }

      if (!hasOverlayLayer) {
        try {
          map.addLayer(
            {
              id: IMG_LAYER_ID,
              type: "raster",
              source: IMG_SOURCE_ID,
              minzoom: minZoom,
              layout: { visibility: "visible" },
              paint: {
                "raster-opacity": targetOpacity > 0 ? targetOpacity : DEFAULT_OVERLAY_OPACITY,
                "raster-resampling": resampling,
                "raster-fade-duration": 0,
              },
            },
            hasLayer(map, "twf-labels") ? "twf-labels" : undefined
          );
        } catch {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
      }

      if (!hasSource(map, IMG_SOURCE_ID) || !hasLayer(map, IMG_LAYER_ID)) {
        overlayReadyRef.current = false;
        (window as any).__twfOverlayReady = false;
        return false;
      }

      const canvas = canvasRef.current;
      if (!canvas) {
        overlayReadyRef.current = false;
        (window as any).__twfOverlayReady = false;
        return false;
      }
      setCanvasSourceCoordinates(map, IMG_SOURCE_ID, canvas, coords);

      try {
        map.setPaintProperty(IMG_LAYER_ID, "raster-resampling", resampling);
        map.setPaintProperty(IMG_LAYER_ID, "raster-fade-duration", 0);
        map.setLayerZoomRange(IMG_LAYER_ID, minZoom, 24);
      } catch {
        overlayReadyRef.current = false;
        (window as any).__twfOverlayReady = false;
        return false;
      }

      overlayReadyRef.current = true;
      (window as any).__twfOverlayReady = true;
      enforceOverlayState(DEFAULT_OVERLAY_OPACITY);
      (window as any).__twfOverlaySourceAUrl = activeImageUrlRef.current;
      if (import.meta.env.DEV && activeImageUrlRef.current) {
        console.info("[MapCanvas] overlay initialized", {
          source: IMG_SOURCE_ID,
          url: activeImageUrlRef.current,
        });
      }
      return true;
    },
    [canMutateMap, enforceOverlayState]
  );

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    const canvas = document.createElement("canvas");
    canvas.width = OVERLAY_CANVAS_WIDTH;
    canvas.height = OVERLAY_CANVAS_HEIGHT;

    // Offscreen composite canvas — all frame compositing happens here first,
    // then the result is atomically blitted to the display canvas so MapLibre
    // never reads a half-drawn intermediate state.
    const compositeCanvas = document.createElement("canvas");
    compositeCanvas.width = OVERLAY_CANVAS_WIDTH;
    compositeCanvas.height = OVERLAY_CANVAS_HEIGHT;

    canvasRef.current = canvas;
    compositeCanvasRef.current = compositeCanvas;
    ctxRef.current = canvas.getContext("2d");

    const mapOptions: any = {
      container: mapContainerRef.current,
      style: styleFor(),
      center: view.center,
      zoom: view.zoom,
      minZoom: 3,
      maxZoom: 11,
      renderWorldCopies: false,
      contextType: "webgl",
      transformRequest: (url: string) => {
        onRequestUrlRef.current?.(url);
        return { url };
      },
    };

    const map = new maplibregl.Map(mapOptions as any);

    mapDestroyedRef.current = false;
    overlayReadyRef.current = false;
    frontFrameRef.current = null;
    backFrameRef.current = null;
    frontFrameUrlRef.current = "";
    (window as any).__twfOverlayReady = false;
    (window as any).__twfOverlaySourceAUrl = "";

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    map.on("load", () => {
      setIsLoaded(true);
      if (import.meta.env.DEV) {
        console.info("[OverlayInit]", { model, variable });
      }
    });

    mapRef.current = map;
    (window as any).__twfMap = map;
  }, [model, variable]);

  useEffect(() => {
    return () => {
      if (animationRafRef.current !== null) {
        window.cancelAnimationFrame(animationRafRef.current);
        animationRafRef.current = null;
      }
      prefetchTokenRef.current += 1;
      renderTokenRef.current += 1;
      mapDestroyedRef.current = true;

      const map = mapRef.current;
      if (map) {
        map.remove();
        mapRef.current = null;
      }

      overlayReadyRef.current = false;
      frontFrameRef.current = null;
      backFrameRef.current = null;
      frontFrameUrlRef.current = "";
      pendingPromotionRef.current = null;
      fadeRef.current = null;
      lastPromoteTimestampRef.current = 0;
      (window as any).__twfOverlayReady = false;
      (window as any).__twfOverlaySourceAUrl = "";
      setIsLoaded(false);
      canvasRef.current = null;
      compositeCanvasRef.current = null;
      ctxRef.current = null;
      for (const [, bitmap] of bitmapCacheRef.current.entries()) {
        try {
          if (bitmap instanceof ImageBitmap) {
            bitmap.close();
          }
        } catch {
          // noop
        }
      }
      bitmapCacheRef.current.clear();
      bitmapCacheOrderRef.current = [];
      inFlightDecodeByUrlRef.current.clear();
      rejectAllDecodeRequests("Overlay decode worker disposed");
      const worker = decodeWorkerRef.current;
      if (worker) {
        try {
          worker.terminate();
        } catch {
          // noop
        }
      }
      decodeWorkerRef.current = null;
      decodeWorkerHealthyRef.current = true;
      frameFailureCountsRef.current.clear();
      if (frameRetryTimerRef.current !== null) {
        window.clearTimeout(frameRetryTimerRef.current);
        frameRetryTimerRef.current = null;
      }
    };
  }, [rejectAllDecodeRequests]);

  useEffect(() => {
    opacityRef.current = opacity;
  }, [opacity]);

  useEffect(() => {
    resamplingModeRef.current = resamplingMode;
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.dataset.resamplingMode = resamplingMode;
    }
    const composite = compositeCanvasRef.current;
    if (composite) {
      composite.dataset.resamplingMode = resamplingMode;
    }
  }, [resamplingMode]);

  useEffect(() => {
    runVarTokenRef.current += 1;
    firstDrawLoggedTokenRef.current = -1;
    firstFramePromotedTokenRef.current = -1;
    firstFramePromotedRef.current = false;
    currentFrameIndexRef.current = -1;
    currentFrameUrlRef.current = "";
    frontFrameUrlRef.current = "";
    frontFrameRef.current = null;
    backFrameRef.current = null;
    activeImageUrlRef.current = "";
    lastDrawnFrameUrlRef.current = "";
    pendingFrameUrlRef.current = "";
    pendingPromotionRef.current = null;
    fadeRef.current = null;
    frameFailureCountsRef.current.clear();
    if (frameRetryTimerRef.current !== null) {
      window.clearTimeout(frameRetryTimerRef.current);
      frameRetryTimerRef.current = null;
    }
    for (const [, bitmap] of bitmapCacheRef.current.entries()) {
      try {
        if (bitmap instanceof ImageBitmap) {
          bitmap.close();
        }
      } catch {
        // noop
      }
    }
    bitmapCacheRef.current.clear();
    bitmapCacheOrderRef.current = [];
    cacheBytesRef.current = 0;
    cacheHitsRef.current = 0;
    cacheMissesRef.current = 0;
    // Discard any in-flight decode promises left over from the previous
    // context so they don't silently insert stale bitmaps (and inflate
    // cacheBytesRef) into the freshly cleared cache.
    inFlightDecodeByUrlRef.current.clear();
    if (import.meta.env.DEV) {
      console.info("[OverlayContextChange]", { model, variable, token: runVarTokenRef.current });
    }
  }, [model, variable]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !onZoomHint) {
      return;
    }

    const lastHintStateRef = { current: false };

    const checkZoom = () => {
      const shouldShow = model === "gfs" && map.getZoom() >= 7;
      if (shouldShow !== lastHintStateRef.current) {
        lastHintStateRef.current = shouldShow;
        onZoomHint(shouldShow);
      }
    };

    map.on("moveend", checkZoom);
    checkZoom();

    return () => {
      map.off("moveend", checkZoom);
      if (lastHintStateRef.current) {
        onZoomHint(false);
      }
    };
  }, [isLoaded, model, onZoomHint]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !isMapStyleReady(map)) {
      return;
    }

    const initialized = ensureOverlayInitialized(
      map,
      imageCoordinates,
      opacity,
      resamplingMode,
      overlayMinZoom
    );
    if (!initialized) {
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas || mapDestroyedRef.current) {
      return;
    }

    setCanvasSourceCoordinates(map, IMG_SOURCE_ID, canvas, imageCoordinates);

    if (hasLayer(map, IMG_LAYER_ID)) {
      map.setPaintProperty(IMG_LAYER_ID, "raster-resampling", resamplingMode);
      map.setPaintProperty(IMG_LAYER_ID, "raster-fade-duration", 0);
      map.setLayerZoomRange(IMG_LAYER_ID, overlayMinZoom, 24);
    }

    if (activeImageUrlRef.current) {
      enforceOverlayState(opacity);
    }
  }, [
    imageCoordinates,
    isLoaded,
    overlayMinZoom,
    resamplingMode,
    opacity,
    enforceOverlayState,
    ensureOverlayInitialized,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !isMapStyleReady(map)) {
      return;
    }

    if (!activeImageUrlRef.current && !pendingFrameUrlRef.current && !pendingPromotionRef.current) {
      hideImageLayers(map);
      if (isMapStyleReady(map)) {
        map.triggerRepaint();
      }
      return;
    }

    enforceOverlayState(opacity);
    if (isMapStyleReady(map)) {
      map.triggerRepaint();
    }
  }, [hideImageLayers, isLoaded, opacity, enforceOverlayState]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !isMapStyleReady(map)) {
      return;
    }

    const token = ++renderTokenRef.current;
    const normalizedFrameImageUrl = frameImageUrl?.trim() ?? "";
    const fallbackFrameUrl = prefetchFrameImageUrls[0]?.trim() ?? "";
    const targetImageUrl = normalizedFrameImageUrl || fallbackFrameUrl;
    pendingFrameUrlRef.current = "";

    if (!targetImageUrl) {
      pendingFrameUrlRef.current = "";
      return;
    }

    const knownIndex = prefetchFrameImageUrls.findIndex((url) => url.trim() === targetImageUrl);
    currentFrameIndexRef.current = knownIndex >= 0 ? knownIndex : 0;
    currentFrameUrlRef.current = targetImageUrl;

    const selectionToken = runVarTokenRef.current;
    if (firstFramePromotedTokenRef.current !== selectionToken || !firstFramePromotedRef.current) {
      firstFramePromotedTokenRef.current = selectionToken;
      firstFramePromotedRef.current = true;
      pendingFrameUrlRef.current = targetImageUrl;
      enforceOverlayState(DEFAULT_OVERLAY_OPACITY);
      map.triggerRepaint();
    }

    // Synchronous fast-path: if the bitmap is already cached, promote it
    // immediately instead of going through the async decode pipeline.
    // This eliminates the ~1-frame microtask delay during scrubbing and
    // playback when frames are pre-fetched.
    const cachedBitmap = bitmapCacheRef.current.get(targetImageUrl);
    if (cachedBitmap) {
      // Only write pendingFrameUrlRef when nothing fresher is already
      // queued.  During playback the promoteFrameRef callback may have
      // already pushed a newer URL — overwriting it with a stale prop
      // value was the root cause of animation freezing at fh0.
      const stale = pendingFrameUrlRef.current && pendingFrameUrlRef.current !== targetImageUrl;
      if (!stale) {
        pendingFrameUrlRef.current = targetImageUrl;
      }
      currentFrameUrlRef.current = targetImageUrl;
      frameFailureCountsRef.current.delete(targetImageUrl);
      onFrameImageReady?.(targetImageUrl);
      map.triggerRepaint();
      return;
    }

    const selectedRunVarToken = runVarTokenRef.current;
    void (async () => {
      try {
        const decoded = await fetchBitmap(targetImageUrl);
        if (token !== renderTokenRef.current || selectedRunVarToken !== runVarTokenRef.current || !canMutateMap(map)) {
          if (!(decoded instanceof ImageBitmap) && !bitmapCacheRef.current.has(targetImageUrl)) {
            // no-op for html image fallback
          }
          return;
        }

        if (import.meta.env.DEV && (window as any).__twfOverlayVerbose === true) {
          const width = (decoded as { width?: number }).width;
          const height = (decoded as { height?: number }).height;
          console.log("[OverlayCanvasDecode]", { w: width, h: height });
        }

        pendingFrameUrlRef.current = targetImageUrl;
        currentFrameUrlRef.current = targetImageUrl;
        frameFailureCountsRef.current.delete(targetImageUrl);
        onFrameImageReady?.(targetImageUrl);
        map.triggerRepaint();
      } catch {
        if (token !== renderTokenRef.current || !canMutateMap(map)) {
          return;
        }
        const failures = (frameFailureCountsRef.current.get(targetImageUrl) ?? 0) + 1;
        frameFailureCountsRef.current.set(targetImageUrl, failures);

        if (failures >= 3) {
          onFrameImageError?.(targetImageUrl);
          activeImageUrlRef.current = "";
          pendingFrameUrlRef.current = "";
          currentFrameUrlRef.current = "";
          currentFrameIndexRef.current = -1;
          hideImageLayers(map);
          map.triggerRepaint();
          return;
        }

        if (frameRetryTimerRef.current !== null) {
          window.clearTimeout(frameRetryTimerRef.current);
        }
        frameRetryTimerRef.current = window.setTimeout(() => {
          frameRetryTimerRef.current = null;
          if (!mapDestroyedRef.current && runVarTokenRef.current === selectedRunVarToken) {
            setRetryNonce((prev) => prev + 1);
          }
        }, 700);
      }
    })();
  }, [
    canMutateMap,
    enforceOverlayState,
    fetchBitmap,
    frameImageUrl,
    hideImageLayers,
    isLoaded,
    onFrameImageError,
    onFrameImageReady,
    prefetchFrameImageUrls,
    retryNonce,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !isMapStyleReady(map)) {
      return;
    }

    const hasFrameList = prefetchFrameImageUrls.length > 0 || Boolean(frameImageUrl?.trim());
    const overlayCanvas = canvasRef.current;
    const compositeCanvas = compositeCanvasRef.current;
    if (!overlayReadyRef.current || !overlayCanvas || !compositeCanvas || !hasFrameList) {
      return;
    }
    rafStartedRef.current = true;

    const tick = (now: number) => {
      if (!canMutateMap(map) || !overlayReadyRef.current) {
        animationRafRef.current = window.requestAnimationFrame(tick);
        return;
      }

      const pendingUrl = pendingFrameUrlRef.current;
      if (pendingUrl) {
        const decoded = bitmapCacheRef.current.get(pendingUrl);
        if (decoded) {
          if (pendingUrl === frontFrameUrlRef.current) {
            pendingFrameUrlRef.current = "";
          } else {
            pendingPromotionRef.current = {
              url: pendingUrl,
              requestedAt: now,
            };
            backFrameRef.current = decoded;
            const hasFrontFrame = Boolean(frontFrameRef.current);
            const shouldCrossfade = crossfade && !isScrubbing && hasFrontFrame;
            if (!shouldCrossfade) {
              frontFrameRef.current = decoded;
              frontFrameUrlRef.current = pendingUrl;
              backFrameRef.current = null;
              fadeRef.current = null;
              drawFrameToCanvas(compositeCanvas, frontFrameRef.current, null, 1, overlayCanvas);
            } else {
              fadeRef.current = {
                startedAt: now,
                durationMs: crossfadeDurationMs,
                targetUrl: pendingUrl,
              };
              drawFrameToCanvas(compositeCanvas, frontFrameRef.current, backFrameRef.current, 0, overlayCanvas);
            }

            playCanvasSources(map);
            map.triggerRepaint();

            lastDrawnFrameUrlRef.current = pendingUrl;
            activeImageUrlRef.current = pendingUrl;
            pendingFrameUrlRef.current = "";
            lastDrawTimestampRef.current = performance.now();
            currentFrameUrlRef.current = pendingUrl;
            const idx = prefetchFrameImageUrls.findIndex((url) => url.trim() === pendingUrl);
            currentFrameIndexRef.current = idx >= 0 ? idx : Math.max(0, currentFrameIndexRef.current);

            if (firstDrawLoggedTokenRef.current !== runVarTokenRef.current) {
              firstDrawLoggedTokenRef.current = runVarTokenRef.current;
              const width = (decoded as { width?: number }).width;
              const height = (decoded as { height?: number }).height;
              console.info("[MapCanvas] first overlay draw ok", {
                index: currentFrameIndexRef.current,
                url: pendingUrl,
                w: width,
                h: height,
              });
            }
          }
        }
      }

      if (pendingPromotionRef.current) {
        const { requestedAt } = pendingPromotionRef.current;
        if (now > requestedAt) {
          pendingPromotionRef.current = null;
          lastPromoteTimestampRef.current = performance.now();
        }
      }

      if (fadeRef.current) {
        const { startedAt, durationMs, targetUrl } = fadeRef.current;

        // Safety guard: if either frame vanished mid-fade, cancel the fade
        // and draw whatever is available at full alpha — never present a
        // blank tick.
        if (!frontFrameRef.current || !backFrameRef.current) {
          const survivor = backFrameRef.current ?? frontFrameRef.current;
          if (survivor === backFrameRef.current && backFrameRef.current) {
            frontFrameRef.current = backFrameRef.current;
            frontFrameUrlRef.current = targetUrl;
          }
          backFrameRef.current = null;
          fadeRef.current = null;
          drawFrameToCanvas(compositeCanvas, frontFrameRef.current, null, 1, overlayCanvas);
          playCanvasSources(map);
          map.triggerRepaint();
          enforceOverlayState(opacityRef.current, { force: true });
        } else {
          const progress = Math.min(1, (now - startedAt) / durationMs);
          drawFrameToCanvas(compositeCanvas, frontFrameRef.current, backFrameRef.current, progress, overlayCanvas);
          playCanvasSources(map);
          map.triggerRepaint();

          if (progress >= 1) {
            frontFrameRef.current = backFrameRef.current;
            frontFrameUrlRef.current = targetUrl;
            backFrameRef.current = null;
            fadeRef.current = null;
            enforceOverlayState(opacityRef.current, { force: true });
          }
        }
      }

      animationRafRef.current = window.requestAnimationFrame(tick);
    };

    animationRafRef.current = window.requestAnimationFrame(tick);
    return () => {
      rafStartedRef.current = false;
      if (animationRafRef.current !== null) {
        window.cancelAnimationFrame(animationRafRef.current);
        animationRafRef.current = null;
      }
    };
  }, [
    canMutateMap,
    crossfade,
    crossfadeDurationMs,
    isScrubbing,
    enforceOverlayState,
    frameImageUrl,
    isLoaded,
    playCanvasSources,
    prefetchFrameImageUrls,
  ]);

  useEffect(() => {
    const token = ++prefetchTokenRef.current;

    const uniqueQueue: string[] = [];
    const seen = new Set<string>();
    for (const rawUrl of prefetchFrameImageUrls) {
      const normalized = rawUrl.trim();
      if (!normalized || seen.has(normalized)) {
        continue;
      }
      seen.add(normalized);
      uniqueQueue.push(normalized);
    }

    if (uniqueQueue.length === 0) {
      return;
    }

    let cancelled = false;

    const runPrefetch = async () => {
      const queueSlice = uniqueQueue.slice(0, PREFETCH_NEARBY_FRAMES);
      let cursor = 0;

      const worker = async () => {
        while (cursor < queueSlice.length) {
          if (cancelled || token !== prefetchTokenRef.current) {
            return;
          }
          const idx = cursor++;
          if (idx >= queueSlice.length) return;
          const url = queueSlice[idx];
          try {
            await fetchBitmap(url);
            onFrameImageReady?.(url);
          } catch {
            // Prefetch failures are non-fatal.
          }
        }
      };

      const workers = Array.from({ length: Math.min(PREFETCH_CONCURRENCY, queueSlice.length) }, () => worker());
      await Promise.allSettled(workers);
    };

    void runPrefetch();

    return () => {
      cancelled = true;
      if (prefetchTokenRef.current === token) {
        prefetchTokenRef.current += 1;
      }
    };
  }, [fetchBitmap, onFrameImageReady, prefetchFrameImageUrls]);

  useEffect(() => {
    (window as any).__twfOverlayDebug = () => {
      const map = mapRef.current;
      const overlayCanvas = canvasRef.current;
      let centerPixel: [number, number, number, number] | null = null;
      let tainted = false;

      if (overlayCanvas) {
        const ctx = overlayCanvas.getContext("2d");
        if (ctx) {
          try {
            const x = Math.max(0, Math.floor(overlayCanvas.width / 2));
            const y = Math.max(0, Math.floor(overlayCanvas.height / 2));
            const data = ctx.getImageData(x, y, 1, 1).data;
            centerPixel = [data[0], data[1], data[2], data[3]];
          } catch {
            tainted = true;
          }
        }
      }

      const totalLookups = cacheHitsRef.current + cacheMissesRef.current;
      return {
        currentFrameUrl: currentFrameUrlRef.current || pendingFrameUrlRef.current || activeImageUrlRef.current,
        currentFrameIndex: currentFrameIndexRef.current,
        framesCount: prefetchFrameImageUrls.length,
        isPlaying: rafStartedRef.current,
        selectionToken: runVarTokenRef.current,
        selectedRun: "unknown-from-map-canvas",
        selectedVar: variable ?? "",
        cacheSize: bitmapCacheRef.current.size,
        cacheBytesUsed: cacheBytesRef.current,
        cacheBudgetBytes: BITMAP_CACHE_BUDGET_BYTES,
        cacheBudgetPct: cacheBytesRef.current / BITMAP_CACHE_BUDGET_BYTES,
        cacheHits: cacheHitsRef.current,
        cacheMisses: cacheMissesRef.current,
        cacheHitRate: totalLookups > 0 ? cacheHitsRef.current / totalLookups : 0,
        lastDrawTimestamp: lastDrawTimestampRef.current,
        lastPromoteTs: lastPromoteTimestampRef.current,
        hasFrontFrame: Boolean(frontFrameRef.current),
        hasBackFrame: Boolean(backFrameRef.current),
        frontFrameUrl: frontFrameUrlRef.current,
        canvasAlpha: sampleCenterAlpha(overlayCanvas),
        canvas: overlayCanvas
          ? {
              width: overlayCanvas.width,
              height: overlayCanvas.height,
              centerPixel,
            }
          : null,
        opacity: map ? map.getPaintProperty(IMG_LAYER_ID, "raster-opacity") : null,
        visibility: map ? map.getLayoutProperty(IMG_LAYER_ID, "visibility") : null,
        tainted,
      };
    };
    return () => {
      delete (window as any).__twfOverlayDebug;
    };
  }, [prefetchFrameImageUrls]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }
    map.easeTo({ center: view.center, zoom: view.zoom, duration: 600 });
  }, [isLoaded, view]);

  return <div ref={mapContainerRef} className="absolute inset-0" aria-label="Weather map" />;
}
