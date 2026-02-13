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
const HIDDEN_OPACITY = 0.001;

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

export type PrefetchFrameImage = {
  tileUrl: string;
  frameImageUrl?: string;
};

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
  prefetchTileUrls?: string[];
  prefetchFrameImages?: PrefetchFrameImage[];
  crossfade?: boolean;
  onFrameSettled?: (tileUrl: string) => void;
  onTileReady?: (tileUrl: string) => void;
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
  prefetchTileUrls = [],
  prefetchFrameImages = [],
  crossfade: _crossfade = false,
  onFrameSettled,
  onTileReady,
  onZoomHint,
  onRequestUrl,
}: MapCanvasProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const canvasElementRef = useRef<HTMLCanvasElement | null>(null);
  const canvasContextRef = useRef<CanvasRenderingContext2D | null>(null);
  const activeOverlayModeRef = useRef<OverlayMode>("tile");

  const renderTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);
  const prefetchTileUrlsRef = useRef<string[]>(Array.from({ length: PREFETCH_TILE_BUFFER_COUNT }, () => ""));

  const activeTileUrlRef = useRef(tileUrl);
  const activeFrameImageUrlRef = useRef<string | null>(null);
  const onRequestUrlRef = useRef(onRequestUrl);

  const imageCacheRef = useRef<Map<string, ImageCacheEntry>>(new Map());
  const imagePendingRef = useRef<Map<string, Promise<boolean>>>(new Map());
  const unavailableFrameImageUrlsRef = useRef<Set<string>>(new Set());

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

  const setLayerOpacity = useCallback((map: maplibregl.Map, id: string, value: number) => {
    if (!map.getLayer(id)) {
      return;
    }
    map.setPaintProperty(id, "raster-opacity", value);
  }, []);

  const setActiveOverlayMode = useCallback(
    (map: maplibregl.Map, modeValue: OverlayMode, targetOpacity: number) => {
      activeOverlayModeRef.current = modeValue;
      setLayerOpacity(map, TILE_LAYER_ID, modeValue === "tile" ? targetOpacity : HIDDEN_OPACITY);
      setLayerOpacity(map, CANVAS_LAYER_ID, modeValue === "canvas" ? targetOpacity : HIDDEN_OPACITY);
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

  const preloadFrameImage = useCallback(
    (url: string): Promise<boolean> => {
      const normalizedUrl = url.trim();
      if (!normalizedUrl) {
        return Promise.resolve(false);
      }

      const cached = imageCacheRef.current.get(normalizedUrl);
      if (cached) {
        touchImageCache(normalizedUrl, cached);
        return Promise.resolve(cached.status === "ready");
      }

      const pending = imagePendingRef.current.get(normalizedUrl);
      if (pending) {
        return pending;
      }

      const promise = new Promise<boolean>((resolve) => {
        const img = new Image();
        img.decoding = "async";
        let done = false;

        const finish = (ok: boolean, bitmap?: ImageBitmap) => {
          if (done) return;
          done = true;
          img.onload = null;
          img.onerror = null;
          imagePendingRef.current.delete(normalizedUrl);

          if (ok && bitmap) {
            unavailableFrameImageUrlsRef.current.delete(normalizedUrl);
            touchImageCache(normalizedUrl, { status: "ready", bitmap });
          } else {
            unavailableFrameImageUrlsRef.current.add(normalizedUrl);
            touchImageCache(normalizedUrl, { status: "error" });
          }

          resolve(ok);
        };

        img.onload = async () => {
          if (typeof createImageBitmap !== "function") {
            finish(false);
            return;
          }
          try {
            const bitmap = await createImageBitmap(img);
            finish(true, bitmap);
          } catch {
            finish(false);
          }
        };

        img.onerror = () => finish(false);
        img.src = normalizedUrl;
      });

      imagePendingRef.current.set(normalizedUrl, promise);
      return promise;
    },
    [touchImageCache]
  );

  const drawImageBitmapToOverlay = useCallback((bitmap: ImageBitmap): boolean => {
    const map = mapRef.current;
    const canvas = canvasElementRef.current;
    const context = canvasContextRef.current;
    if (!map || !canvas || !context) {
      return false;
    }

    if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
      canvas.width = Math.max(1, bitmap.width);
      canvas.height = Math.max(1, bitmap.height);
    }

    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    map.triggerRepaint();
    return true;
  }, []);

  const ensureCanvasOverlay = useCallback(
    (map: maplibregl.Map) => {
      const existing = map.getSource(CANVAS_SOURCE_ID) as MutableCanvasSource | undefined;
      if (existing) {
        existing.setCoordinates?.(imageCoordinates);
        return;
      }

      const canvas = document.createElement("canvas");
      canvas.width = 2;
      canvas.height = 2;
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
      imagePendingRef.current.clear();
      unavailableFrameImageUrlsRef.current.clear();
      canvasElementRef.current = null;
      canvasContextRef.current = null;
      setIsLoaded(false);
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

    map.setPaintProperty(TILE_LAYER_ID, "raster-resampling", resamplingMode);
    map.setLayerZoomRange(TILE_LAYER_ID, overlayMinZoom, 24);

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

    const showCanvasFrame = (imageUrl: string): boolean => {
      const entry = imageCacheRef.current.get(imageUrl);
      if (!entry || entry.status !== "ready" || !entry.bitmap) {
        return false;
      }
      touchImageCache(imageUrl, entry);

      if (!drawImageBitmapToOverlay(entry.bitmap)) {
        return false;
      }

      if (token !== renderTokenRef.current) {
        return false;
      }

      setActiveOverlayMode(map, "canvas", opacity);
      activeTileUrlRef.current = tileUrl;
      activeFrameImageUrlRef.current = imageUrl;
      onTileReady?.(tileUrl);
      onFrameSettled?.(tileUrl);
      return true;
    };

    const showFallbackTile = () => {
      if (token !== renderTokenRef.current) {
        return;
      }

      const source = map.getSource(TILE_SOURCE_ID);
      if (!setOverlaySourceUrl(source, tileUrl)) {
        return;
      }

      setActiveOverlayMode(map, "tile", opacity);
      activeTileUrlRef.current = tileUrl;
      activeFrameImageUrlRef.current = null;
      onTileReady?.(tileUrl);
      settledCleanup = notifyTileSettled(map, tileUrl, token);
    };

    const normalizedImageUrl = frameImageUrl?.trim() || "";
    const canUseImage =
      preferFrameImages &&
      normalizedImageUrl.length > 0 &&
      !unavailableFrameImageUrlsRef.current.has(normalizedImageUrl);

    if (
      canUseImage &&
      activeOverlayModeRef.current === "canvas" &&
      activeTileUrlRef.current === tileUrl &&
      activeFrameImageUrlRef.current === normalizedImageUrl
    ) {
      setActiveOverlayMode(map, "canvas", opacity);
      onTileReady?.(tileUrl);
      onFrameSettled?.(tileUrl);
      return () => {
        settledCleanup?.();
      };
    }

    if (canUseImage && showCanvasFrame(normalizedImageUrl)) {
      return () => {
        settledCleanup?.();
      };
    }

    if (canUseImage) {
      preloadFrameImage(normalizedImageUrl)
        .then((ready) => {
          if (token !== renderTokenRef.current) {
            return;
          }
          if (ready && showCanvasFrame(normalizedImageUrl)) {
            return;
          }
          showFallbackTile();
        })
        .catch(() => {
          if (token !== renderTokenRef.current) {
            return;
          }
          showFallbackTile();
        });
    } else {
      showFallbackTile();
    }

    return () => {
      settledCleanup?.();
    };
  }, [
    tileUrl,
    frameImageUrl,
    preferFrameImages,
    mode,
    opacity,
    drawImageBitmapToOverlay,
    touchImageCache,
    preloadFrameImage,
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
    if (prefetchFrameImages.length === 0) {
      return;
    }

    const token = ++prefetchTokenRef.current;
    const queue = prefetchFrameImages
      .filter((item) => item.frameImageUrl && item.frameImageUrl.trim())
      .filter((item) => !unavailableFrameImageUrlsRef.current.has(item.frameImageUrl!.trim()));

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
        const imageUrl = item.frameImageUrl?.trim();
        if (!imageUrl) {
          continue;
        }

        const ready = await preloadFrameImage(imageUrl);
        if (token !== prefetchTokenRef.current) {
          return;
        }

        if (ready) {
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
    };
  }, [prefetchFrameImages, preloadFrameImage, onTileReady]);

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
