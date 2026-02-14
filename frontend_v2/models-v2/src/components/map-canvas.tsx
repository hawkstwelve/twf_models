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

const IMAGE_PREFETCH_THROTTLE_MS = 24;
const HIDDEN_OPACITY = 0;
const DEFAULT_OVERLAY_OPACITY = 0.85;
const OVERLAY_CANVAS_WIDTH = 2048;
const OVERLAY_CANVAS_HEIGHT = 2046;
const BITMAP_CACHE_LIMIT = 12;
const PREFETCH_NEARBY_FRAMES = 8;

const IMG_SOURCE_A = "twf-canvas-a";
const IMG_SOURCE_B = "twf-canvas-b";
const IMG_LAYER_A = "twf-img-a";
const IMG_LAYER_B = "twf-img-b";

type ActiveImageBuffer = "a" | "b";
type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];
type DecodedFrame = ImageBitmap | HTMLImageElement;

type MutableCanvasSource = maplibregl.CanvasSource & {
  setCoordinates?: (coordinates: ImageCoordinates) => void;
  play?: () => void;
};

function getResamplingMode(variable?: string): "nearest" | "linear" {
  if (variable && (variable.includes("radar") || variable.includes("ptype"))) {
    return "nearest";
  }
  return "nearest";
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

function drawFrameToCanvas(canvas: HTMLCanvasElement, img: CanvasImageSource): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("2D canvas context unavailable for overlay draw");
  }
  const w = canvas.width;
  const h = canvas.height;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.imageSmoothingEnabled = canvas.dataset.resamplingMode !== "nearest";
  ctx.drawImage(img, 0, 0, w, h);
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
  const activeLayerRef = useRef<"twf-img-a" | "twf-img-b">("twf-img-a");
  const activeImageUrlRef = useRef<string>("");
  const renderTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);
  const bitmapCacheRef = useRef<Map<string, DecodedFrame>>(new Map());
  const bitmapCacheOrderRef = useRef<string[]>([]);
  const cacheHitsRef = useRef(0);
  const cacheMissesRef = useRef(0);
  const pendingFrameUrlRef = useRef<string>("");
  const lastDrawnFrameUrlRef = useRef<string>("");
  const lastDrawTimestampRef = useRef<number>(0);
  const opacityRef = useRef(opacity);
  const resamplingModeRef = useRef<"nearest" | "linear">("nearest");
  const runVarTokenRef = useRef(0);
  const activeBufferRef = useRef<ActiveImageBuffer>("a");
  const frontIdRef = useRef<ActiveImageBuffer>("a");
  const currentFrameIndexRef = useRef<number>(-1);
  const currentFrameUrlRef = useRef<string>("");
  const firstDrawLoggedTokenRef = useRef<number>(-1);
  const firstFramePromotedTokenRef = useRef<number>(-1);
  const firstFramePromotedRef = useRef(false);
  const rafStartedRef = useRef(false);
  const bufferHasContentRef = useRef<{ a: boolean; b: boolean }>({ a: false, b: false });
  const bufferNonBlankRef = useRef<{ a: boolean; b: boolean }>({ a: false, b: false });
  const pendingPromotionRef = useRef<{
    url: string;
    backBuffer: ActiveImageBuffer;
    requestedAt: number;
  } | null>(null);
  const lastPromoteTimestampRef = useRef<number>(0);
  const frameFailureCountsRef = useRef<Map<string, number>>(new Map());
  const frameRetryTimerRef = useRef<number | null>(null);
  const fadeRef = useRef<{
    fromLayer: "twf-img-a" | "twf-img-b";
    toLayer: "twf-img-a" | "twf-img-b";
    startedAt: number;
    durationMs: number;
  } | null>(null);
  const animationRafRef = useRef<number | null>(null);

  const canvasARef = useRef<HTMLCanvasElement | null>(null);
  const canvasBRef = useRef<HTMLCanvasElement | null>(null);
  const ctxARef = useRef<CanvasRenderingContext2D | null>(null);
  const ctxBRef = useRef<CanvasRenderingContext2D | null>(null);

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
    (targetOpacity: number) => {
      const map = mapRef.current;
      if (!map || !canMutateMap(map) || !overlayReadyRef.current) {
        return;
      }

      const active = activeLayerRef.current;
      const inactive = active === IMG_LAYER_A ? IMG_LAYER_B : IMG_LAYER_A;

      if (!map.getLayer(active) || !map.getLayer(inactive)) {
        return;
      }

      try {
        const effectiveOpacity = targetOpacity > 0 ? targetOpacity : DEFAULT_OVERLAY_OPACITY;
        map.setLayoutProperty(active, "visibility", "visible");
        map.setLayoutProperty(inactive, "visibility", "visible");
        map.setPaintProperty(active, "raster-opacity", effectiveOpacity);
        map.setPaintProperty(inactive, "raster-opacity", HIDDEN_OPACITY);

        const opacityA = Number(map.getPaintProperty(IMG_LAYER_A, "raster-opacity") ?? 0);
        const opacityB = Number(map.getPaintProperty(IMG_LAYER_B, "raster-opacity") ?? 0);
        const overlayActive = Boolean(activeImageUrlRef.current || pendingFrameUrlRef.current);
        if (overlayActive && opacityA === 0 && opacityB === 0) {
          map.setPaintProperty(IMG_LAYER_A, "raster-opacity", DEFAULT_OVERLAY_OPACITY);
          activeLayerRef.current = IMG_LAYER_A;
          activeBufferRef.current = "a";
          frontIdRef.current = "a";
        }

        if (import.meta.env.DEV) {
          const op = map.getPaintProperty(activeLayerRef.current, "raster-opacity");
          if (op === 0) {
            console.error("Overlay active layer opacity is 0 — THIS SHOULD NEVER HAPPEN");
          }
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
      try {
        if (cached instanceof ImageBitmap) {
          cached.close();
        }
      } catch {
        // noop
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

  const fetchBitmap = useCallback(async (url: string): Promise<DecodedFrame> => {
    const cached = bitmapCacheRef.current.get(url);
    if (cached) {
      cacheHitsRef.current += 1;
      bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== url);
      bitmapCacheOrderRef.current.push(url);
      return cached;
    }
    cacheMissesRef.current += 1;

    let decoded: DecodedFrame;
    if (typeof createImageBitmap === "function") {
      const response = await fetch(url, { mode: "cors", credentials: "omit", cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Failed to fetch overlay bitmap (${response.status} ${response.statusText}) for ${url}`);
      }
      const blob = await response.blob();
      decoded = await createImageBitmap(blob);
    } else {
      decoded = await decodeWithImageElement(url);
    }

    bitmapCacheRef.current.set(url, decoded);
    bitmapCacheOrderRef.current.push(url);

    while (bitmapCacheOrderRef.current.length > BITMAP_CACHE_LIMIT) {
      const evictedUrl = bitmapCacheOrderRef.current.shift();
      if (!evictedUrl) {
        break;
      }
      removeBitmapFromCache(evictedUrl);
    }

    return decoded;
  }, [decodeWithImageElement, removeBitmapFromCache]);

  const playCanvasSources = useCallback((map: maplibregl.Map) => {
    const sourceA = map.getSource(IMG_SOURCE_A) as MutableCanvasSource | undefined;
    const sourceB = map.getSource(IMG_SOURCE_B) as MutableCanvasSource | undefined;
    sourceA?.play?.();
    sourceB?.play?.();
  }, []);

  const hideImageLayers = useCallback(
    (map: maplibregl.Map) => {
      if (
        !overlayReadyRef.current ||
        !isMapStyleReady(map) ||
        !hasSource(map, IMG_SOURCE_A) ||
        !hasSource(map, IMG_SOURCE_B) ||
        !hasLayer(map, IMG_LAYER_A) ||
        !hasLayer(map, IMG_LAYER_B)
      ) {
        return;
      }
      setLayerVisibility(map, IMG_LAYER_A, false);
      setLayerVisibility(map, IMG_LAYER_B, false);
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

      const hasSourceA = hasSource(map, IMG_SOURCE_A);
      const hasSourceB = hasSource(map, IMG_SOURCE_B);
      const hasLayerA = hasLayer(map, IMG_LAYER_A);
      const hasLayerB = hasLayer(map, IMG_LAYER_B);
      const overlayPresent = hasSourceA && hasSourceB && hasLayerA && hasLayerB;

      if (overlayReadyRef.current && overlayPresent) {
        const canvasA = canvasARef.current;
        const canvasB = canvasBRef.current;
        if (!canvasA || !canvasB) {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
        setCanvasSourceCoordinates(map, IMG_SOURCE_A, canvasA, coords);
        setCanvasSourceCoordinates(map, IMG_SOURCE_B, canvasB, coords);
        try {
          map.setPaintProperty(IMG_LAYER_A, "raster-resampling", resampling);
          map.setPaintProperty(IMG_LAYER_A, "raster-fade-duration", 0);
          map.setLayerZoomRange(IMG_LAYER_A, minZoom, 24);
          map.setPaintProperty(IMG_LAYER_B, "raster-resampling", resampling);
          map.setPaintProperty(IMG_LAYER_B, "raster-fade-duration", 0);
          map.setLayerZoomRange(IMG_LAYER_B, minZoom, 24);
        } catch {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
        (window as any).__twfOverlayReady = true;
        enforceOverlayState(targetOpacity);
        return true;
      }

      if (!(hasSourceA && hasSourceB)) {
        const canvasA = canvasARef.current;
        const canvasB = canvasBRef.current;
        if (!canvasA || !canvasB) {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
        try {
          if (!hasSourceA) {
            map.addSource(IMG_SOURCE_A, canvasSourceFor(canvasA, coords));
          }
          if (!hasSourceB) {
            map.addSource(IMG_SOURCE_B, canvasSourceFor(canvasB, coords));
          }
        } catch {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
      }

      if (!(hasLayerA && hasLayerB)) {
        try {
          if (!hasLayerA) {
            map.addLayer(
              {
                id: IMG_LAYER_A,
                type: "raster",
                source: IMG_SOURCE_A,
                minzoom: minZoom,
                layout: { visibility: "visible" },
                paint: {
                  "raster-opacity": HIDDEN_OPACITY,
                  "raster-resampling": resampling,
                  "raster-fade-duration": 0,
                },
              },
              hasLayer(map, "twf-labels") ? "twf-labels" : undefined
            );
          }
          if (!hasLayerB) {
            map.addLayer(
              {
                id: IMG_LAYER_B,
                type: "raster",
                source: IMG_SOURCE_B,
                minzoom: minZoom,
                layout: { visibility: "visible" },
                paint: {
                  "raster-opacity": HIDDEN_OPACITY,
                  "raster-resampling": resampling,
                  "raster-fade-duration": 0,
                },
              },
              hasLayer(map, "twf-labels") ? "twf-labels" : undefined
            );
          }
        } catch {
          overlayReadyRef.current = false;
          (window as any).__twfOverlayReady = false;
          return false;
        }
      }

      if (!hasSource(map, IMG_SOURCE_A) || !hasSource(map, IMG_SOURCE_B) || !hasLayer(map, IMG_LAYER_A) || !hasLayer(map, IMG_LAYER_B)) {
        overlayReadyRef.current = false;
        (window as any).__twfOverlayReady = false;
        return false;
      }

      const canvasA = canvasARef.current;
      const canvasB = canvasBRef.current;
      if (!canvasA || !canvasB) {
        overlayReadyRef.current = false;
        (window as any).__twfOverlayReady = false;
        return false;
      }
      setCanvasSourceCoordinates(map, IMG_SOURCE_A, canvasA, coords);
      setCanvasSourceCoordinates(map, IMG_SOURCE_B, canvasB, coords);
      activeLayerRef.current = IMG_LAYER_A;

      try {
        map.setPaintProperty(IMG_LAYER_A, "raster-resampling", resampling);
        map.setPaintProperty(IMG_LAYER_A, "raster-fade-duration", 0);
        map.setLayerZoomRange(IMG_LAYER_A, minZoom, 24);
        map.setPaintProperty(IMG_LAYER_B, "raster-resampling", resampling);
        map.setPaintProperty(IMG_LAYER_B, "raster-fade-duration", 0);
        map.setLayerZoomRange(IMG_LAYER_B, minZoom, 24);
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
          source: IMG_SOURCE_A,
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

    const canvasA = document.createElement("canvas");
    const canvasB = document.createElement("canvas");
    canvasA.width = OVERLAY_CANVAS_WIDTH;
    canvasA.height = OVERLAY_CANVAS_HEIGHT;
    canvasB.width = OVERLAY_CANVAS_WIDTH;
    canvasB.height = OVERLAY_CANVAS_HEIGHT;

    canvasARef.current = canvasA;
    canvasBRef.current = canvasB;
    ctxARef.current = canvasA.getContext("2d");
    ctxBRef.current = canvasB.getContext("2d");

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
    activeLayerRef.current = IMG_LAYER_A;
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
      activeLayerRef.current = IMG_LAYER_A;
      activeBufferRef.current = "a";
      frontIdRef.current = "a";
      bufferHasContentRef.current = { a: false, b: false };
      bufferNonBlankRef.current = { a: false, b: false };
      pendingPromotionRef.current = null;
      fadeRef.current = null;
      lastPromoteTimestampRef.current = 0;
      (window as any).__twfOverlayReady = false;
      (window as any).__twfOverlaySourceAUrl = "";
      setIsLoaded(false);
      canvasARef.current = null;
      canvasBRef.current = null;
      ctxARef.current = null;
      ctxBRef.current = null;
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
      frameFailureCountsRef.current.clear();
      if (frameRetryTimerRef.current !== null) {
        window.clearTimeout(frameRetryTimerRef.current);
        frameRetryTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    opacityRef.current = opacity;
  }, [opacity]);

  useEffect(() => {
    resamplingModeRef.current = resamplingMode;
    const canvasA = canvasARef.current;
    const canvasB = canvasBRef.current;
    if (canvasA) {
      canvasA.dataset.resamplingMode = resamplingMode;
    }
    if (canvasB) {
      canvasB.dataset.resamplingMode = resamplingMode;
    }
  }, [resamplingMode]);

  useEffect(() => {
    runVarTokenRef.current += 1;
    firstDrawLoggedTokenRef.current = -1;
    firstFramePromotedTokenRef.current = -1;
    firstFramePromotedRef.current = false;
    currentFrameIndexRef.current = -1;
    currentFrameUrlRef.current = "";
    pendingFrameUrlRef.current = "";
    pendingPromotionRef.current = null;
    fadeRef.current = null;
    bufferHasContentRef.current = { a: false, b: false };
    bufferNonBlankRef.current = { a: false, b: false };
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

    const canvasA = canvasARef.current;
    const canvasB = canvasBRef.current;
    if (!canvasA || !canvasB || mapDestroyedRef.current) {
      return;
    }

    setCanvasSourceCoordinates(map, IMG_SOURCE_A, canvasA, imageCoordinates);
    setCanvasSourceCoordinates(map, IMG_SOURCE_B, canvasB, imageCoordinates);

    if (hasLayer(map, IMG_LAYER_A)) {
      map.setPaintProperty(IMG_LAYER_A, "raster-resampling", resamplingMode);
      map.setPaintProperty(IMG_LAYER_A, "raster-fade-duration", 0);
      map.setLayerZoomRange(IMG_LAYER_A, overlayMinZoom, 24);
    }

    if (hasLayer(map, IMG_LAYER_B)) {
      map.setPaintProperty(IMG_LAYER_B, "raster-resampling", resamplingMode);
      map.setPaintProperty(IMG_LAYER_B, "raster-fade-duration", 0);
      map.setLayerZoomRange(IMG_LAYER_B, overlayMinZoom, 24);
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
    const hasValidFrameIndex = currentFrameIndexRef.current >= 0;
    if (!overlayReadyRef.current || !hasFrameList || !hasValidFrameIndex) {
      return;
    }
    rafStartedRef.current = true;

    const tick = (now: number) => {
      if (!canMutateMap(map) || !overlayReadyRef.current) {
        animationRafRef.current = window.requestAnimationFrame(tick);
        return;
      }

      const pendingUrl = pendingFrameUrlRef.current;
      if (pendingUrl && pendingUrl !== lastDrawnFrameUrlRef.current) {
        const decoded = bitmapCacheRef.current.get(pendingUrl);
        if (decoded) {
          const frontBuffer: ActiveImageBuffer = frontIdRef.current;
          const backBuffer: ActiveImageBuffer = frontBuffer === "a" ? "b" : "a";
          const frontLayer = frontBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
          const backLayer = backBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
          const nextCanvas = backBuffer === "a" ? canvasARef.current : canvasBRef.current;
          if (nextCanvas) {
            if (import.meta.env.DEV && (window as any).__twfOverlayVerbose === true) {
              console.log("[OverlayCanvasFrame]", { frameImageUrl: pendingUrl, nextBuffer: backBuffer });
            }

            const frontOpacity = Number(map.getPaintProperty(frontLayer, "raster-opacity") ?? 0);
            if (frontOpacity > 0.05 && backBuffer === frontBuffer) {
              if ((window as any).__twfOverlayVerbose === true) {
                console.warn("[PROMOTE BLOCKED]", { reason: "draw attempted on front buffer", frontBuffer, backBuffer });
              }
              animationRafRef.current = window.requestAnimationFrame(tick);
              return;
            }
            nextCanvas.dataset.resamplingMode = resamplingModeRef.current;
            drawFrameToCanvas(nextCanvas, decoded);
            const alpha = sampleCenterAlpha(nextCanvas);
            const backIsNonBlank = isCanvasNonBlank(nextCanvas);
            bufferHasContentRef.current[backBuffer] = true;
            bufferNonBlankRef.current[backBuffer] = backIsNonBlank;
            if (!backIsNonBlank && (window as any).__twfOverlayVerbose === true) {
              console.warn("[PROMOTE BLOCKED]", {
                reason: "blank back sample; allowing promotion after successful draw",
                url: pendingUrl,
                backBuffer,
                alpha,
              });
            }

            if (import.meta.env.DEV && (window as any).__twfOverlayVerbose === true) {
              try {
                const sample = nextCanvas.getContext("2d")?.getImageData(0, 0, 2, 2)?.data;
                let nonZero = 0;
                if (sample) {
                  for (let i = 0; i < sample.length; i += 1) {
                    if (sample[i] !== 0) {
                      nonZero += 1;
                    }
                  }
                }
                console.log("[OverlayCanvasDraw]", { nonZero });
                if (nonZero === 0) {
                  console.warn("[OverlayCanvasDraw] all-zero sample after draw", { url: pendingUrl });
                }
              } catch {
                console.warn("[OverlayCanvasDraw] sampling failed", { url: pendingUrl });
              }
            }

            playCanvasSources(map);
            map.triggerRepaint();

            pendingPromotionRef.current = {
              url: pendingUrl,
              backBuffer,
              requestedAt: now,
            };

            lastDrawnFrameUrlRef.current = pendingUrl;
            activeImageUrlRef.current = pendingUrl;
            pendingFrameUrlRef.current = "";
            lastDrawTimestampRef.current = performance.now();
            currentFrameUrlRef.current = pendingUrl;
            const idx = prefetchFrameImageUrls.findIndex((url) => url.trim() === pendingUrl);
            currentFrameIndexRef.current = idx >= 0 ? idx : Math.max(0, currentFrameIndexRef.current);
            map.triggerRepaint();

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

            if (import.meta.env.DEV && (window as any).__twfOverlayVerbose === true) {
              console.log("[OverlayCanvasApply]", {
                opacityA: map.getPaintProperty(IMG_LAYER_A, "raster-opacity"),
                opacityB: map.getPaintProperty(IMG_LAYER_B, "raster-opacity"),
                visibilityA: map.getLayoutProperty(IMG_LAYER_A, "visibility"),
                visibilityB: map.getLayoutProperty(IMG_LAYER_B, "visibility"),
              });
            }
          }
        }
      }

      if (pendingPromotionRef.current) {
        const { backBuffer, requestedAt, url } = pendingPromotionRef.current;
        if (now > requestedAt) {
          const backHasContent = bufferHasContentRef.current[backBuffer];
          if (!backHasContent) {
            console.warn("[PROMOTE BLOCKED]", { reason: "promotion without back content", backBuffer, url });
          } else {
            const frontBuffer: ActiveImageBuffer = frontIdRef.current;
            const frontLayer = frontBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
            const backLayer = backBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
            const frontCanvas = frontBuffer === "a" ? canvasARef.current : canvasBRef.current;
            const backCanvas = backBuffer === "a" ? canvasARef.current : canvasBRef.current;
            const target = Math.max(opacityRef.current, DEFAULT_OVERLAY_OPACITY);
            const canCrossfade =
              crossfade &&
              Boolean(frontCanvas && backCanvas && isCanvasNonBlank(frontCanvas) && isCanvasNonBlank(backCanvas));

            try {
              setLayerVisibility(map, IMG_LAYER_A, true);
              setLayerVisibility(map, IMG_LAYER_B, true);
              if (canCrossfade) {
                map.setPaintProperty(frontLayer, "raster-opacity", Math.max(target, 0.05));
                map.setPaintProperty(backLayer, "raster-opacity", Math.max(target, 0.05));
              } else {
                frontIdRef.current = backBuffer;
                activeBufferRef.current = backBuffer;
                activeLayerRef.current = backLayer;
                map.setPaintProperty(backLayer, "raster-opacity", target);
                map.setPaintProperty(frontLayer, "raster-opacity", 0);
                const hiddenBuffer: ActiveImageBuffer = backBuffer === "a" ? "b" : "a";
                bufferHasContentRef.current[hiddenBuffer] = false;
                bufferNonBlankRef.current[hiddenBuffer] = false;
              }
            } catch {
              // noop
            }

            fadeRef.current = canCrossfade
              ? {
                  fromLayer: frontLayer,
                  toLayer: backLayer,
                  startedAt: now,
                  durationMs: 120,
                }
              : null;
            pendingPromotionRef.current = null;
            lastPromoteTimestampRef.current = performance.now();
          }
        }
      }

      if (fadeRef.current) {
        const { fromLayer, toLayer, startedAt, durationMs } = fadeRef.current;
        const progress = Math.min(1, (now - startedAt) / durationMs);
        try {
          const target = Math.max(opacityRef.current, DEFAULT_OVERLAY_OPACITY);
          const fromOpacity = Math.max(0, target * (1 - progress));
          const toOpacity = target;
          map.setPaintProperty(fromLayer, "raster-opacity", fromOpacity);
          map.setPaintProperty(toLayer, "raster-opacity", toOpacity);
          if (fromOpacity < 0.05 && toOpacity < 0.05) {
            map.setPaintProperty(toLayer, "raster-opacity", 0.05);
          }
        } catch {
          fadeRef.current = null;
        }

        if (progress >= 1) {
          activeLayerRef.current = toLayer;
          activeBufferRef.current = toLayer === IMG_LAYER_A ? "a" : "b";
          frontIdRef.current = activeBufferRef.current;
          const hiddenBuffer: ActiveImageBuffer = activeBufferRef.current === "a" ? "b" : "a";
          bufferHasContentRef.current[hiddenBuffer] = false;
          bufferNonBlankRef.current[hiddenBuffer] = false;
          enforceOverlayState(opacityRef.current);
          fadeRef.current = null;
        }
        map.triggerRepaint();
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
      for (const url of queueSlice) {
        if (cancelled || token !== prefetchTokenRef.current) {
          return;
        }
        try {
          await fetchBitmap(url);
          onFrameImageReady?.(url);
        } catch {
          // Prefetch failures are non-fatal and should not mark a frame unavailable.
        }
        if (cancelled || token !== prefetchTokenRef.current) {
          return;
        }
        await new Promise<void>((resolve) => {
          window.setTimeout(() => resolve(), IMAGE_PREFETCH_THROTTLE_MS);
        });
      }
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
      const activeCanvas = activeBufferRef.current === "a" ? canvasARef.current : canvasBRef.current;
      const canvasA = canvasARef.current;
      const canvasB = canvasBRef.current;
      let centerPixel: [number, number, number, number] | null = null;
      let tainted = false;

      if (activeCanvas) {
        const ctx = activeCanvas.getContext("2d");
        if (ctx) {
          try {
            const x = Math.max(0, Math.floor(activeCanvas.width / 2));
            const y = Math.max(0, Math.floor(activeCanvas.height / 2));
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
        cacheHits: cacheHitsRef.current,
        cacheMisses: cacheMissesRef.current,
        cacheHitRate: totalLookups > 0 ? cacheHitsRef.current / totalLookups : 0,
        lastDrawTimestamp: lastDrawTimestampRef.current,
        lastPromoteTs: lastPromoteTimestampRef.current,
        front: activeBufferRef.current,
        back: activeBufferRef.current === "a" ? "b" : "a",
        frontId: frontIdRef.current,
        frontIsNonBlank: bufferNonBlankRef.current[frontIdRef.current],
        backIsNonBlank: bufferNonBlankRef.current[frontIdRef.current === "a" ? "b" : "a"],
        frontAlpha: sampleCenterAlpha(frontIdRef.current === "a" ? canvasA : canvasB),
        backAlpha: sampleCenterAlpha(frontIdRef.current === "a" ? canvasB : canvasA),
        frontHasContent: bufferHasContentRef.current[activeBufferRef.current],
        backHasContent: bufferHasContentRef.current[activeBufferRef.current === "a" ? "b" : "a"],
        aA: sampleCenterAlpha(canvasA),
        aB: sampleCenterAlpha(canvasB),
        canvas: activeCanvas
          ? {
              width: activeCanvas.width,
              height: activeCanvas.height,
              centerPixel,
            }
          : null,
        opacityA: map ? map.getPaintProperty(IMG_LAYER_A, "raster-opacity") : null,
        opacityB: map ? map.getPaintProperty(IMG_LAYER_B, "raster-opacity") : null,
        frontOpacity:
          map && frontIdRef.current === "a"
            ? map.getPaintProperty(IMG_LAYER_A, "raster-opacity")
            : map
              ? map.getPaintProperty(IMG_LAYER_B, "raster-opacity")
              : null,
        backOpacity:
          map && frontIdRef.current === "a"
            ? map.getPaintProperty(IMG_LAYER_B, "raster-opacity")
            : map
              ? map.getPaintProperty(IMG_LAYER_A, "raster-opacity")
              : null,
        opA: map ? map.getPaintProperty(IMG_LAYER_A, "raster-opacity") : null,
        opB: map ? map.getPaintProperty(IMG_LAYER_B, "raster-opacity") : null,
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
