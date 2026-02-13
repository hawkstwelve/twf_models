import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type StyleSpecification } from "maplibre-gl";

import { DEFAULTS } from "@/lib/config";
import { ensurePmtilesProtocol } from "@/lib/pmtiles";

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

const TILE_SETTLE_TIMEOUT_MS = 1200;
const PREFETCH_TILE_BUFFER_COUNT = 4;
const IMAGE_PREFETCH_CONCURRENCY = 4;
const IMAGE_CACHE_MAX_ENTRIES = 40;

const CANVAS_POT_BASE_SIZE = 2048;
const CANVAS_POT_DPR_REDUCED_SIZE = 1024;
const HIDDEN_OPACITY = 0.001;
const DEV_STATS_LOG_INTERVAL_MS = 2000;

const TILE_SOURCE_ID = "twf-overlay-tile";
const TILE_LAYER_ID = "twf-overlay-tile";
const CANVAS_SOURCE_ID = "twf-overlay-canvas";
const CANVAS_LAYER_ID = "twf-overlay-canvas";

type OverlayMode = "tile" | "canvas";
type PlaybackMode = "autoplay" | "scrub";
type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];

type MutableRasterSource = maplibregl.RasterTileSource & {
  setTiles?: (tiles: string[]) => maplibregl.RasterTileSource;
  setUrl?: (url: string) => maplibregl.RasterTileSource;
};

type MutableCanvasSource = maplibregl.CanvasSource & {
  setCoordinates?: (coordinates: ImageCoordinates) => void;
};

type ImageCacheEntry = {
  status: "ready" | "error";
  bitmap?: ImageBitmap;
};

type LoadResult = "ready" | "aborted" | "http_error" | "decode_error" | "network_error";

type DevStats = {
  canvasDrawHits: number;
  canvasDrawMisses: number;
  tileFallbackCount: number;
  httpErrorCount: number;
  decodeErrorCount: number;
  abortCount: number;
};

export type PrefetchFrameImage = {
  tileUrl: string;
  frameImageUrl?: string;
};

let cachedMaxTextureSize: number | null | undefined;

function detectMaxTextureSize(): number | null {
  if (cachedMaxTextureSize !== undefined) {
    return cachedMaxTextureSize;
  }

  try {
    const canvas = document.createElement("canvas");
    const gl =
      canvas.getContext("webgl2", { preserveDrawingBuffer: false }) ||
      canvas.getContext("webgl", { preserveDrawingBuffer: false });
    if (!gl) {
      cachedMaxTextureSize = null;
      return cachedMaxTextureSize;
    }
    const max = gl.getParameter(gl.MAX_TEXTURE_SIZE);
    cachedMaxTextureSize = typeof max === "number" && Number.isFinite(max) ? max : null;
    return cachedMaxTextureSize;
  } catch {
    cachedMaxTextureSize = null;
    return cachedMaxTextureSize;
  }
}

function floorPowerOfTwo(value: number): number {
  if (!Number.isFinite(value) || value <= 1) {
    return 1;
  }
  return 2 ** Math.floor(Math.log2(value));
}

function resolveCanvasPotSize(): number {
  const dpr = window.devicePixelRatio || 1;
  let preferred = dpr >= 2.5 ? CANVAS_POT_DPR_REDUCED_SIZE : CANVAS_POT_BASE_SIZE;

  const maxTextureSize = detectMaxTextureSize();
  if (typeof maxTextureSize === "number" && maxTextureSize > 0) {
    preferred = Math.min(preferred, maxTextureSize);
  }

  return floorPowerOfTwo(Math.max(1, preferred));
}

function prefetchSourceId(index: number): string {
  return `twf-prefetch-${index}`;
}

function prefetchLayerId(index: number): string {
  return `twf-prefetch-${index}`;
}

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

function overlaySourceFor(url: string, bounds?: [number, number, number, number]) {
  return {
    type: "raster",
    url,
    tileSize: 256,
    bounds,
  };
}

function setOverlaySourceUrl(source: maplibregl.Source | undefined, url: string): boolean {
  const rasterSource = source as MutableRasterSource | undefined;
  if (!rasterSource) {
    return false;
  }
  if (typeof rasterSource.setUrl === "function") {
    rasterSource.setUrl(url);
    return true;
  }
  if (typeof rasterSource.setTiles === "function") {
    rasterSource.setTiles([url]);
    return true;
  }
  return false;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function styleFor(
  tileUrl: string,
  opacity: number,
  variable?: string,
  model?: string,
  region?: string
): StyleSpecification {
  const resamplingMode = getResamplingMode(variable);
  const overlayBounds = (region && REGION_BOUNDS[region]) || REGION_BOUNDS.pnw;
  const overlayMinZoom = model === "gfs" ? 6 : 3;

  const prefetchSources = Object.fromEntries(
    Array.from({ length: PREFETCH_TILE_BUFFER_COUNT }, (_, idx) => [
      prefetchSourceId(idx + 1),
      overlaySourceFor(tileUrl, overlayBounds),
    ])
  );

  const prefetchLayers = Array.from({ length: PREFETCH_TILE_BUFFER_COUNT }, (_, idx) => ({
    id: prefetchLayerId(idx + 1),
    type: "raster" as const,
    source: prefetchSourceId(idx + 1),
    minzoom: overlayMinZoom,
    paint: {
      "raster-opacity": HIDDEN_OPACITY,
      "raster-resampling": resamplingMode,
      "raster-fade-duration": 0,
    },
  }));

  return {
    version: 8,
    sources: {
      "twf-basemap": {
        type: "raster",
        tiles: CARTO_LIGHT_BASE_TILES,
        tileSize: 256,
        attribution: BASEMAP_ATTRIBUTION,
      },
      [TILE_SOURCE_ID]: overlaySourceFor(tileUrl, overlayBounds),
      ...prefetchSources,
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
        id: TILE_LAYER_ID,
        type: "raster" as const,
        source: TILE_SOURCE_ID,
        minzoom: overlayMinZoom,
        paint: {
          "raster-opacity": opacity,
          "raster-resampling": resamplingMode,
          "raster-fade-duration": 0,
        },
      },
      ...prefetchLayers,
      {
        id: "twf-labels",
        type: "raster" as const,
        source: "twf-labels",
      },
    ],
  };
}

type MapCanvasProps = {
  tileUrl: string;
  frameImageUrl?: string;
  region: string;
  opacity: number;
  mode: PlaybackMode;
  variable?: string;
  model?: string;
  preferFrameImages?: boolean;
  scrubIsActive?: boolean;
  prefetchTileUrls?: string[];
  prefetchFrameImages?: PrefetchFrameImage[];
  crossfade?: boolean;
  onFrameSettled?: (tileUrl: string) => void;
  onTileReady?: (tileUrl: string) => void;
  onFrameImageReady?: (imageUrl: string) => void;
  onZoomHint?: (show: boolean) => void;
  onRequestUrl?: (url: string) => void;
};

export function MapCanvas({
  tileUrl,
  frameImageUrl,
  region,
  opacity,
  mode,
  variable,
  model,
  preferFrameImages = true,
  scrubIsActive = false,
  prefetchTileUrls = [],
  prefetchFrameImages = [],
  crossfade: _crossfade = false,
  onFrameSettled,
  onTileReady,
  onFrameImageReady,
  onZoomHint,
  onRequestUrl,
}: MapCanvasProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const canvasPotSizeRef = useRef(resolveCanvasPotSize());
  const canvasElementRef = useRef<HTMLCanvasElement | null>(null);
  const canvasContextRef = useRef<CanvasRenderingContext2D | null>(null);

  const activeOverlayModeRef = useRef<OverlayMode>("tile");
  const activeTileUrlRef = useRef(tileUrl);
  const activeFrameImageUrlRef = useRef<string | null>(null);
  const lastCanvasImageUrlRef = useRef<string | null>(null);

  const renderTokenRef = useRef(0);
  const renderAbortControllerRef = useRef<AbortController | null>(null);

  const prefetchTokenRef = useRef(0);
  const prefetchAbortControllersRef = useRef<Set<AbortController>>(new Set());
  const prefetchTileUrlsRef = useRef<string[]>(Array.from({ length: PREFETCH_TILE_BUFFER_COUNT }, () => ""));

  const imageCacheRef = useRef<Map<string, ImageCacheEntry>>(new Map());
  const failedFrameImageUrlsRef = useRef<Set<string>>(new Set());
  const onRequestUrlRef = useRef(onRequestUrl);

  const devStatsRef = useRef<DevStats>({
    canvasDrawHits: 0,
    canvasDrawMisses: 0,
    tileFallbackCount: 0,
    httpErrorCount: 0,
    decodeErrorCount: 0,
    abortCount: 0,
  });

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

  const bumpStat = useCallback((name: keyof DevStats) => {
    if (!import.meta.env.DEV) {
      return;
    }
    devStatsRef.current[name] += 1;
  }, []);

  const setLayerOpacity = useCallback((map: maplibregl.Map, id: string, value: number) => {
    if (!map.getLayer(id)) {
      return;
    }
    map.setPaintProperty(id, "raster-opacity", value);
  }, []);

  const setActiveOverlayMode = useCallback(
    (map: maplibregl.Map, modeValue: OverlayMode, targetOpacity: number) => {
      activeOverlayModeRef.current = modeValue;
      if (map.getLayer(TILE_LAYER_ID)) {
        setLayerOpacity(map, TILE_LAYER_ID, modeValue === "tile" ? targetOpacity : HIDDEN_OPACITY);
      }
      if (map.getLayer(CANVAS_LAYER_ID)) {
        setLayerOpacity(map, CANVAS_LAYER_ID, modeValue === "canvas" ? targetOpacity : HIDDEN_OPACITY);
      }
    },
    [setLayerOpacity]
  );

  const touchImageCache = useCallback((url: string, entry: ImageCacheEntry) => {
    const cache = imageCacheRef.current;
    cache.delete(url);
    cache.set(url, entry);

    while (cache.size > IMAGE_CACHE_MAX_ENTRIES) {
      const oldestUrl = cache.keys().next().value as string | undefined;
      if (!oldestUrl) {
        break;
      }
      const evicted = cache.get(oldestUrl);
      if (evicted?.bitmap) {
        evicted.bitmap.close();
      }
      cache.delete(oldestUrl);
    }
  }, []);

  const setImageBitmapInCache = useCallback(
    (url: string, bitmap: ImageBitmap) => {
      const cache = imageCacheRef.current;
      const previous = cache.get(url);
      if (previous?.bitmap && previous.bitmap !== bitmap) {
        previous.bitmap.close();
      }
      touchImageCache(url, { status: "ready", bitmap });
    },
    [touchImageCache]
  );

  const loadFrameImageToCache = useCallback(
    async (url: string, signal: AbortSignal): Promise<LoadResult> => {
      const normalizedUrl = url.trim();
      if (!normalizedUrl) {
        return "network_error";
      }

      const cached = imageCacheRef.current.get(normalizedUrl);
      if (cached?.status === "ready" && cached.bitmap) {
        touchImageCache(normalizedUrl, cached);
        onFrameImageReady?.(normalizedUrl);
        return "ready";
      }

      if (failedFrameImageUrlsRef.current.has(normalizedUrl)) {
        return "http_error";
      }

      if (signal.aborted) {
        bumpStat("abortCount");
        return "aborted";
      }

      let response: Response;
      try {
        response = await fetch(normalizedUrl, { signal, credentials: "omit" });
      } catch (error) {
        if (isAbortError(error) || signal.aborted) {
          bumpStat("abortCount");
          return "aborted";
        }
        bumpStat("httpErrorCount");
        return "network_error";
      }

      if (!response.ok) {
        failedFrameImageUrlsRef.current.add(normalizedUrl);
        touchImageCache(normalizedUrl, { status: "error" });
        bumpStat("httpErrorCount");
        return "http_error";
      }

      let blob: Blob;
      try {
        blob = await response.blob();
      } catch (error) {
        if (isAbortError(error) || signal.aborted) {
          bumpStat("abortCount");
          return "aborted";
        }
        bumpStat("httpErrorCount");
        return "network_error";
      }

      let bitmap: ImageBitmap;
      try {
        bitmap = await createImageBitmap(blob);
      } catch {
        failedFrameImageUrlsRef.current.add(normalizedUrl);
        touchImageCache(normalizedUrl, { status: "error" });
        bumpStat("decodeErrorCount");
        return "decode_error";
      }

      if (signal.aborted) {
        bitmap.close();
        bumpStat("abortCount");
        return "aborted";
      }

      failedFrameImageUrlsRef.current.delete(normalizedUrl);
      setImageBitmapInCache(normalizedUrl, bitmap);
      onFrameImageReady?.(normalizedUrl);
      return "ready";
    },
    [bumpStat, touchImageCache, setImageBitmapInCache, onFrameImageReady]
  );

  const drawImageBitmapToOverlay = useCallback((bitmap: ImageBitmap): boolean => {
    const map = mapRef.current;
    const canvas = canvasElementRef.current;
    const context = canvasContextRef.current;
    if (!map || !canvas || !context) {
      return false;
    }

    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    map.triggerRepaint();
    return true;
  }, []);

  const ensureCanvasOverlay = useCallback(
    (map: maplibregl.Map) => {
      const existingSource = map.getSource(CANVAS_SOURCE_ID) as MutableCanvasSource | undefined;
      if (existingSource) {
        existingSource.setCoordinates?.(imageCoordinates);
        return;
      }

      const size = canvasPotSizeRef.current;
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext("2d", { alpha: true });
      if (!context) {
        return;
      }

      canvasElementRef.current = canvas;
      canvasContextRef.current = context;

      map.addSource(
        CANVAS_SOURCE_ID,
        {
          type: "canvas",
          canvas,
          coordinates: imageCoordinates,
          animate: false,
        } as any
      );

      map.addLayer(
        {
          id: CANVAS_LAYER_ID,
          type: "raster",
          source: CANVAS_SOURCE_ID,
          minzoom: overlayMinZoom,
          paint: {
            "raster-opacity": HIDDEN_OPACITY,
            "raster-resampling": resamplingMode,
            "raster-fade-duration": 0,
          },
        } as any,
        "twf-labels"
      );
    },
    [imageCoordinates, overlayMinZoom, resamplingMode]
  );

  const notifyTileSettled = useCallback(
    (map: maplibregl.Map, url: string, token: number) => {
      let done = false;
      let timeoutId: number | null = null;

      const cleanup = () => {
        map.off("sourcedata", onSourceData);
        if (timeoutId !== null) {
          window.clearTimeout(timeoutId);
          timeoutId = null;
        }
      };

      const fire = () => {
        if (done) return;
        if (token !== renderTokenRef.current) {
          cleanup();
          return;
        }
        done = true;
        cleanup();
        onFrameSettled?.(url);
      };

      const onSourceData = (event: maplibregl.MapSourceDataEvent) => {
        if (event.sourceId !== TILE_SOURCE_ID) {
          return;
        }
        if (map.isSourceLoaded(TILE_SOURCE_ID)) {
          window.requestAnimationFrame(fire);
        }
      };

      if (map.isSourceLoaded(TILE_SOURCE_ID)) {
        window.requestAnimationFrame(fire);
        return () => {
          done = true;
          cleanup();
        };
      }

      map.on("sourcedata", onSourceData);
      timeoutId = window.setTimeout(fire, TILE_SETTLE_TIMEOUT_MS);

      return () => {
        done = true;
        cleanup();
      };
    },
    [onFrameSettled]
  );

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }
    if (!tileUrl) {
      return;
    }

    ensurePmtilesProtocol();

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: styleFor(tileUrl, opacity, variable, model, region),
      center: view.center,
      zoom: view.zoom,
      minZoom: 3,
      maxZoom: 11,
      renderWorldCopies: false,
      transformRequest: (url) => {
        onRequestUrlRef.current?.(url);
        return { url };
      },
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

    map.on("load", () => {
      ensureCanvasOverlay(map);
      setIsLoaded(true);
    });

    mapRef.current = map;
  }, [tileUrl, opacity, variable, model, region, view.center, view.zoom, ensureCanvasOverlay]);

  useEffect(() => {
    return () => {
      renderAbortControllerRef.current?.abort();
      renderAbortControllerRef.current = null;

      for (const controller of prefetchAbortControllersRef.current) {
        controller.abort();
      }
      prefetchAbortControllersRef.current.clear();

      const map = mapRef.current;
      if (map) {
        map.remove();
        mapRef.current = null;
      }

      for (const entry of imageCacheRef.current.values()) {
        if (entry.bitmap) {
          entry.bitmap.close();
        }
      }
      imageCacheRef.current.clear();
      failedFrameImageUrlsRef.current.clear();
      canvasElementRef.current = null;
      canvasContextRef.current = null;
      setIsLoaded(false);
    };
  }, []);

  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }

    const interval = window.setInterval(() => {
      const stats = devStatsRef.current;
      const drawBase = stats.canvasDrawHits + stats.tileFallbackCount;
      const canvasPct = drawBase > 0 ? Math.round((stats.canvasDrawHits / drawBase) * 1000) / 10 : 0;
      console.debug("[map][canvas-stats]", {
        ...stats,
        canvasUsagePct: canvasPct,
        cacheSize: imageCacheRef.current.size,
        activeOverlayMode: activeOverlayModeRef.current,
      });
    }, DEV_STATS_LOG_INTERVAL_MS);

    return () => {
      window.clearInterval(interval);
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
    if (!map || !isLoaded) {
      return;
    }

    ensureCanvasOverlay(map);

    const source = map.getSource(CANVAS_SOURCE_ID) as MutableCanvasSource | undefined;
    source?.setCoordinates?.(imageCoordinates);

    if (map.getLayer(TILE_LAYER_ID)) {
      map.setPaintProperty(TILE_LAYER_ID, "raster-resampling", resamplingMode);
      map.setLayerZoomRange(TILE_LAYER_ID, overlayMinZoom, 24);
    }

    if (map.getLayer(CANVAS_LAYER_ID)) {
      map.setPaintProperty(CANVAS_LAYER_ID, "raster-resampling", resamplingMode);
      map.setLayerZoomRange(CANVAS_LAYER_ID, overlayMinZoom, 24);
    }

    for (let idx = 1; idx <= PREFETCH_TILE_BUFFER_COUNT; idx += 1) {
      const layer = prefetchLayerId(idx);
      if (!map.getLayer(layer)) continue;
      map.setPaintProperty(layer, "raster-resampling", resamplingMode);
      map.setLayerZoomRange(layer, overlayMinZoom, 24);
    }
  }, [isLoaded, ensureCanvasOverlay, imageCoordinates, resamplingMode, overlayMinZoom]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !tileUrl) {
      return;
    }

    const token = ++renderTokenRef.current;
    let settledCleanup: (() => void) | undefined;

    renderAbortControllerRef.current?.abort();
    const renderController = new AbortController();
    renderAbortControllerRef.current = renderController;

    const normalizedImageUrl = frameImageUrl?.trim() || "";
    const shouldTryCanvas = preferFrameImages && normalizedImageUrl.length > 0;
    const realErrorForRequestedUrl =
      normalizedImageUrl.length > 0 && failedFrameImageUrlsRef.current.has(normalizedImageUrl);
    const holdCanvasDuringScrub = shouldTryCanvas && scrubIsActive && mode === "scrub";

    const drawCanvasUrl = (imageUrl: string, countHit = true): boolean => {
      const entry = imageCacheRef.current.get(imageUrl);
      if (!entry || entry.status !== "ready" || !entry.bitmap) {
        if (countHit) {
          bumpStat("canvasDrawMisses");
        }
        return false;
      }

      touchImageCache(imageUrl, entry);
      const drawn = drawImageBitmapToOverlay(entry.bitmap);
      if (!drawn) {
        if (countHit) {
          bumpStat("canvasDrawMisses");
        }
        return false;
      }

      if (token !== renderTokenRef.current) {
        return false;
      }

      if (countHit) {
        bumpStat("canvasDrawHits");
      }
      setActiveOverlayMode(map, "canvas", opacity);
      activeTileUrlRef.current = tileUrl;
      activeFrameImageUrlRef.current = imageUrl;
      lastCanvasImageUrlRef.current = imageUrl;
      onTileReady?.(tileUrl);
      onFrameSettled?.(tileUrl);
      return true;
    };

    const holdLastCanvasFrame = (): boolean => {
      const lastUrl = lastCanvasImageUrlRef.current;
      if (!lastUrl) {
        return false;
      }
      return drawCanvasUrl(lastUrl, false);
    };

    const fallbackToTile = () => {
      if (token !== renderTokenRef.current) {
        return;
      }

      const source = map.getSource(TILE_SOURCE_ID);
      if (!setOverlaySourceUrl(source, tileUrl)) {
        return;
      }

      bumpStat("tileFallbackCount");
      setActiveOverlayMode(map, "tile", opacity);
      activeTileUrlRef.current = tileUrl;
      activeFrameImageUrlRef.current = null;
      onTileReady?.(tileUrl);
      settledCleanup = notifyTileSettled(map, tileUrl, token);
    };

    if (shouldTryCanvas && drawCanvasUrl(normalizedImageUrl)) {
      return () => {
        renderController.abort();
        if (renderAbortControllerRef.current === renderController) {
          renderAbortControllerRef.current = null;
        }
        settledCleanup?.();
      };
    }

    if (shouldTryCanvas) {
      void loadFrameImageToCache(normalizedImageUrl, renderController.signal)
        .then((result) => {
          if (token !== renderTokenRef.current) {
            return;
          }

          if (result === "ready") {
            drawCanvasUrl(normalizedImageUrl);
            return;
          }

          if (result === "aborted") {
            if (holdCanvasDuringScrub) {
              holdLastCanvasFrame();
            }
            return;
          }

          const isRealError = result === "http_error" || result === "decode_error" || realErrorForRequestedUrl;
          if (holdCanvasDuringScrub && !isRealError) {
            holdLastCanvasFrame();
            return;
          }

          fallbackToTile();
        })
        .catch((error) => {
          if (token !== renderTokenRef.current) {
            return;
          }
          if (isAbortError(error)) {
            bumpStat("abortCount");
            if (holdCanvasDuringScrub) {
              holdLastCanvasFrame();
            }
            return;
          }
          if (holdCanvasDuringScrub) {
            holdLastCanvasFrame();
            return;
          }
          fallbackToTile();
        });

      if (holdCanvasDuringScrub) {
        holdLastCanvasFrame();
      }
    } else {
      fallbackToTile();
    }

    return () => {
      renderController.abort();
      if (renderAbortControllerRef.current === renderController) {
        renderAbortControllerRef.current = null;
      }
      settledCleanup?.();
    };
  }, [
    tileUrl,
    frameImageUrl,
    mode,
    opacity,
    preferFrameImages,
    scrubIsActive,
    drawImageBitmapToOverlay,
    touchImageCache,
    bumpStat,
    loadFrameImageToCache,
    setActiveOverlayMode,
    notifyTileSettled,
    onTileReady,
    onFrameSettled,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    const urls = Array.from({ length: PREFETCH_TILE_BUFFER_COUNT }, (_, idx) => prefetchTileUrls[idx] ?? "");
    urls.forEach((url, idx) => {
      if (!url || prefetchTileUrlsRef.current[idx] === url) {
        return;
      }
      prefetchTileUrlsRef.current[idx] = url;
      const source = map.getSource(prefetchSourceId(idx + 1));
      setOverlaySourceUrl(source, url);
    });
  }, [prefetchTileUrls, isLoaded]);

  useEffect(() => {
    const previousControllers = prefetchAbortControllersRef.current;
    for (const controller of previousControllers) {
      controller.abort();
    }
    previousControllers.clear();

    if (prefetchFrameImages.length === 0) {
      return;
    }

    const token = ++prefetchTokenRef.current;

    const queue = prefetchFrameImages
      .filter((item) => item.frameImageUrl && item.frameImageUrl.trim())
      .map((item) => ({
        tileUrl: item.tileUrl,
        frameImageUrl: item.frameImageUrl!.trim(),
      }));

    if (queue.length === 0) {
      return;
    }

    let cursor = 0;

    const runWorker = async () => {
      while (token === prefetchTokenRef.current) {
        const index = cursor;
        cursor += 1;
        if (index >= queue.length) {
          break;
        }

        const item = queue[index];
        const imageUrl = item.frameImageUrl;

        const cached = imageCacheRef.current.get(imageUrl);
        if (cached?.status === "ready") {
          onFrameImageReady?.(imageUrl);
          onTileReady?.(item.tileUrl);
          continue;
        }

        if (failedFrameImageUrlsRef.current.has(imageUrl)) {
          continue;
        }

        const controller = new AbortController();
        prefetchAbortControllersRef.current.add(controller);

        const result = await loadFrameImageToCache(imageUrl, controller.signal);

        prefetchAbortControllersRef.current.delete(controller);

        if (token !== prefetchTokenRef.current) {
          return;
        }

        if (result === "ready") {
          onTileReady?.(item.tileUrl);
        }
      }
    };

    const workerCount = Math.min(IMAGE_PREFETCH_CONCURRENCY, queue.length);
    for (let i = 0; i < workerCount; i += 1) {
      void runWorker();
    }

    return () => {
      if (prefetchTokenRef.current === token) {
        prefetchTokenRef.current += 1;
      }
      for (const controller of prefetchAbortControllersRef.current) {
        controller.abort();
      }
      prefetchAbortControllersRef.current.clear();
    };
  }, [prefetchFrameImages, loadFrameImageToCache, onFrameImageReady, onTileReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    setLayerOpacity(map, TILE_LAYER_ID, HIDDEN_OPACITY);
    if (map.getLayer(CANVAS_LAYER_ID)) {
      setLayerOpacity(map, CANVAS_LAYER_ID, HIDDEN_OPACITY);
    }

    for (let idx = 1; idx <= PREFETCH_TILE_BUFFER_COUNT; idx += 1) {
      setLayerOpacity(map, prefetchLayerId(idx), HIDDEN_OPACITY);
    }

    setActiveOverlayMode(map, activeOverlayModeRef.current, opacity);
  }, [opacity, isLoaded, setLayerOpacity, setActiveOverlayMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }
    map.easeTo({ center: view.center, zoom: view.zoom, duration: 600 });
  }, [view, isLoaded]);

  return <div ref={mapContainerRef} className="absolute inset-0" aria-label="Weather map" />;
}
