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
const OVERLAY_CANVAS_WIDTH = 2048;
const OVERLAY_CANVAS_HEIGHT = 2046;
const BITMAP_CACHE_LIMIT = 12;

const IMG_SOURCE_A = "twf-canvas-a";
const IMG_SOURCE_B = "twf-canvas-b";
const IMG_LAYER_A = "twf-img-a";
const IMG_LAYER_B = "twf-img-b";

type ActiveImageBuffer = "a" | "b";
type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];

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

  try {
    const layerId = sourceId === IMG_SOURCE_A ? IMG_LAYER_A : sourceId === IMG_SOURCE_B ? IMG_LAYER_B : undefined;
    if (layerId && hasLayer(map, layerId)) {
      map.removeLayer(layerId);
    }
    if (hasSource(map, sourceId)) {
      map.removeSource(sourceId);
    }
    map.addSource(sourceId, canvasSourceFor(canvas, coordinates));
    if (layerId && !hasLayer(map, layerId)) {
      map.addLayer(
        {
          id: layerId,
          type: "raster",
          source: sourceId,
          paint: {
            "raster-opacity": HIDDEN_OPACITY,
            "raster-resampling": "nearest",
            "raster-fade-duration": 0,
          },
        },
        hasLayer(map, "twf-labels") ? "twf-labels" : undefined
      );
    }
    return true;
  } catch {
    return false;
  }
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

  const onRequestUrlRef = useRef(onRequestUrl);
  const activeLayerRef = useRef<"twf-img-a" | "twf-img-b">("twf-img-a");
  const activeImageUrlRef = useRef<string>("");
  const renderTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);
  const bitmapCacheRef = useRef<Map<string, ImageBitmap>>(new Map());
  const bitmapCacheOrderRef = useRef<string[]>([]);

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
        map.setLayoutProperty(active, "visibility", "visible");
        map.setLayoutProperty(inactive, "visibility", "visible");
        map.setPaintProperty(active, "raster-opacity", targetOpacity);
        map.setPaintProperty(inactive, "raster-opacity", HIDDEN_OPACITY);

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
        cached.close();
      } catch {
        // noop
      }
      bitmapCacheRef.current.delete(url);
    }
    bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== url);
  }, []);

  const fetchBitmap = useCallback(async (url: string): Promise<ImageBitmap> => {
    const cached = bitmapCacheRef.current.get(url);
    if (cached) {
      bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== url);
      bitmapCacheOrderRef.current.push(url);
      return cached;
    }

    const response = await fetch(url, { mode: "cors", credentials: "omit", cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to fetch overlay bitmap (${response.status} ${response.statusText}) for ${url}`);
    }
    const blob = await response.blob();
    const bitmap = await createImageBitmap(blob);

    bitmapCacheRef.current.set(url, bitmap);
    bitmapCacheOrderRef.current.push(url);

    while (bitmapCacheOrderRef.current.length > BITMAP_CACHE_LIMIT) {
      const evictedUrl = bitmapCacheOrderRef.current.shift();
      if (!evictedUrl) {
        break;
      }
      removeBitmapFromCache(evictedUrl);
    }

    return bitmap;
  }, [removeBitmapFromCache]);

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
      enforceOverlayState(targetOpacity);
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
    });

    mapRef.current = map;
    (window as any).__twfMap = map;
  }, []);

  useEffect(() => {
    return () => {
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
      (window as any).__twfOverlayReady = false;
      (window as any).__twfOverlaySourceAUrl = "";
      setIsLoaded(false);
      canvasARef.current = null;
      canvasBRef.current = null;
      ctxARef.current = null;
      ctxBRef.current = null;
      for (const [, bitmap] of bitmapCacheRef.current.entries()) {
        try {
          bitmap.close();
        } catch {
          // noop
        }
      }
      bitmapCacheRef.current.clear();
      bitmapCacheOrderRef.current = [];
    };
  }, []);

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
  }, [imageCoordinates, isLoaded, overlayMinZoom, resamplingMode, opacity, enforceOverlayState]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !isMapStyleReady(map)) {
      return;
    }

    if (!activeImageUrlRef.current) {
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
    const targetImageUrl = frameImageUrl?.trim() ?? "";

    if (!targetImageUrl) {
      activeImageUrlRef.current = "";
      hideImageLayers(map);
      if (isMapStyleReady(map)) {
        map.triggerRepaint();
      }
      return;
    }

    if (activeImageUrlRef.current === targetImageUrl) {
      enforceOverlayState(opacity);
      if (isMapStyleReady(map)) {
        map.triggerRepaint();
      }
      return;
    }

    void (async () => {
        if (token !== renderTokenRef.current || !canMutateMap(map)) {
          if (token === renderTokenRef.current && canMutateMap(map)) {
            activeImageUrlRef.current = "";
            hideImageLayers(map);
            map.triggerRepaint();
          }
          return;
        }

        const alternateLayer: "twf-img-a" | "twf-img-b" =
          activeLayerRef.current === IMG_LAYER_A ? IMG_LAYER_B : IMG_LAYER_A;
        const nextLayer: "twf-img-a" | "twf-img-b" = crossfade ? alternateLayer : activeLayerRef.current;
        const nextBuffer: ActiveImageBuffer = nextLayer === IMG_LAYER_A ? "a" : "b";
        if (import.meta.env.DEV) {
          console.log("[OverlayCanvasFrame]", { frameImageUrl: targetImageUrl, nextBuffer });
        }

        const targetCanvas = nextBuffer === "a" ? canvasARef.current : canvasBRef.current;
        if (!targetCanvas) {
          onFrameImageError?.(targetImageUrl);
          activeImageUrlRef.current = "";
          hideImageLayers(map);
          map.triggerRepaint();
          return;
        }

        targetCanvas.dataset.resamplingMode = resamplingMode;

        let bitmap: ImageBitmap | null = null;
        const hadCachedBeforeFetch = bitmapCacheRef.current.has(targetImageUrl);
        try {
          bitmap = await fetchBitmap(targetImageUrl);
        } catch {
          onFrameImageError?.(targetImageUrl);
          activeImageUrlRef.current = "";
          hideImageLayers(map);
          map.triggerRepaint();
          return;
        }

        if (import.meta.env.DEV) {
          console.log("[OverlayCanvasDecode]", { w: bitmap.width, h: bitmap.height });
        }

        if (token !== renderTokenRef.current || !canMutateMap(map)) {
          if (!hadCachedBeforeFetch) {
            if (bitmapCacheRef.current.get(targetImageUrl) === bitmap) {
              bitmapCacheRef.current.delete(targetImageUrl);
              bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== targetImageUrl);
            }
            bitmap.close();
          }
          return;
        }

        const initialized = ensureOverlayInitialized(
          map,
          imageCoordinates,
          opacity,
          resamplingMode,
          overlayMinZoom
        );
        if (!initialized || !overlayReadyRef.current || !canMutateMap(map)) {
          if (!hadCachedBeforeFetch) {
            if (bitmapCacheRef.current.get(targetImageUrl) === bitmap) {
              bitmapCacheRef.current.delete(targetImageUrl);
              bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== targetImageUrl);
            }
            bitmap.close();
          }
          if (token === renderTokenRef.current && canMutateMap(map)) {
            activeImageUrlRef.current = "";
            hideImageLayers(map);
            map.triggerRepaint();
          }
          return;
        }

        try {
          drawFrameToCanvas(targetCanvas, bitmap);
        } catch {
          if (!hadCachedBeforeFetch) {
            if (bitmapCacheRef.current.get(targetImageUrl) === bitmap) {
              bitmapCacheRef.current.delete(targetImageUrl);
              bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== targetImageUrl);
            }
            bitmap.close();
          }
          onFrameImageError?.(targetImageUrl);
          activeImageUrlRef.current = "";
          hideImageLayers(map);
          map.triggerRepaint();
          return;
        }

        if (!canMutateMap(map)) {
          if (!hadCachedBeforeFetch) {
            if (bitmapCacheRef.current.get(targetImageUrl) === bitmap) {
              bitmapCacheRef.current.delete(targetImageUrl);
              bitmapCacheOrderRef.current = bitmapCacheOrderRef.current.filter((entry) => entry !== targetImageUrl);
            }
            bitmap.close();
          }
          return;
        }

        if (import.meta.env.DEV) {
          try {
            const sample = targetCanvas.getContext("2d")?.getImageData(0, 0, 2, 2)?.data;
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
              console.warn("[OverlayCanvasDraw] all-zero sample after draw", { url: targetImageUrl });
            }
          } catch {
            console.warn("[OverlayCanvasDraw] sampling failed", { url: targetImageUrl });
          }
        }

        playCanvasSources(map);

        activeLayerRef.current = nextLayer;
        activeImageUrlRef.current = targetImageUrl;
        setLayerVisibility(map, IMG_LAYER_A, true);
        setLayerVisibility(map, IMG_LAYER_B, true);
        enforceOverlayState(opacity);
        map.triggerRepaint();

        if (import.meta.env.DEV) {
          console.log("[OverlayCanvasApply]", {
            opacityA: map.getPaintProperty(IMG_LAYER_A, "raster-opacity"),
            opacityB: map.getPaintProperty(IMG_LAYER_B, "raster-opacity"),
            visibilityA: map.getLayoutProperty(IMG_LAYER_A, "visibility"),
            visibilityB: map.getLayoutProperty(IMG_LAYER_B, "visibility"),
          });
        }
        onFrameImageReady?.(targetImageUrl);
      })()
      .catch(() => {
        if (token !== renderTokenRef.current || !canMutateMap(map)) {
          return;
        }
        activeImageUrlRef.current = "";
        hideImageLayers(map);
        map.triggerRepaint();
      });
  }, [
    crossfade,
    canMutateMap,
    frameImageUrl,
    hideImageLayers,
    imageCoordinates,
    isLoaded,
    onFrameImageError,
    onFrameImageReady,
    opacity,
    overlayMinZoom,
    resamplingMode,
    fetchBitmap,
    playCanvasSources,
    enforceOverlayState,
    ensureOverlayInitialized,
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
      for (const url of uniqueQueue) {
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
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }
    map.easeTo({ center: view.center, zoom: view.zoom, duration: 600 });
  }, [isLoaded, view]);

  return <div ref={mapContainerRef} className="absolute inset-0" aria-label="Weather map" />;
}
