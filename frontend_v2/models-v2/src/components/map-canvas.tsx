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
const IMAGE_SOURCE_SETTLE_TIMEOUT_MS = 1500;
const PREFETCH_TILE_BUFFER_COUNT = 4;
const IMAGE_CACHE_MAX_ENTRIES = 40;
const IMAGE_CROSSFADE_DURATION_MS = 60;
const IMAGE_PREFETCH_THROTTLE_MS = 24;
const MAX_IMAGE_TEXTURE_SIZE = 4096;
const HIDDEN_OPACITY = 0;
const TRANSPARENT_IMAGE_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVQImWP8z/D/PwMDAwMjIAMAFAIB7l9d0QAAAABJRU5ErkJggg==";

const TILE_SOURCE_ID = "twf-overlay-tile";
const TILE_LAYER_ID = "twf-overlay-tile";
const IMG_SOURCE_A = "twf-img-a";
const IMG_SOURCE_B = "twf-img-b";
const IMG_LAYER_A = "twf-img-a";
const IMG_LAYER_B = "twf-img-b";

type OverlayMode = "tile" | "image";
type ActiveImageBuffer = "a" | "b";
type PlaybackMode = "autoplay" | "scrub";
type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];

type MutableRasterSource = maplibregl.RasterTileSource & {
  setTiles?: (tiles: string[]) => maplibregl.RasterTileSource;
  setUrl?: (url: string) => maplibregl.RasterTileSource;
};

type MutableImageSource = maplibregl.ImageSource & {
  updateImage?: (options: { url: string; coordinates: ImageCoordinates }) => maplibregl.ImageSource;
  setCoordinates?: (coordinates: ImageCoordinates) => void;
};

type PreparedImage = {
  mapUrl: string;
  revokeUrl?: string;
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

function imageSourceFor(url: string, coordinates: ImageCoordinates) {
  return {
    type: "image",
    url,
    coordinates,
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

function setImageSourceUrl(
  source: maplibregl.Source | undefined,
  url: string,
  coordinates: ImageCoordinates
): boolean {
  const imageSource = source as MutableImageSource | undefined;
  if (!imageSource) {
    return false;
  }
  if (typeof imageSource.updateImage === "function") {
    imageSource.updateImage({ url, coordinates });
    return true;
  }
  return false;
}

function isPowerOfTwo(value: number): boolean {
  if (!Number.isFinite(value) || value < 1) {
    return false;
  }
  return (value & (value - 1)) === 0;
}

function nextPowerOfTwo(value: number): number {
  if (!Number.isFinite(value) || value <= 1) {
    return 1;
  }
  return 2 ** Math.ceil(Math.log2(value));
}

async function createPotImageBlobUrl(image: HTMLImageElement): Promise<string | null> {
  const width = Math.max(1, image.naturalWidth || image.width || 1);
  const height = Math.max(1, image.naturalHeight || image.height || 1);
  if (isPowerOfTwo(width) && isPowerOfTwo(height)) {
    return null;
  }

  const potWidth = Math.max(1, Math.min(MAX_IMAGE_TEXTURE_SIZE, nextPowerOfTwo(width)));
  const potHeight = Math.max(1, Math.min(MAX_IMAGE_TEXTURE_SIZE, nextPowerOfTwo(height)));

  const canvas = document.createElement("canvas");
  canvas.width = potWidth;
  canvas.height = potHeight;
  const context = canvas.getContext("2d", { alpha: true });
  if (!context) {
    return null;
  }

  context.clearRect(0, 0, potWidth, potHeight);
  context.drawImage(image, 0, 0, potWidth, potHeight);

  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob((nextBlob) => resolve(nextBlob), "image/webp", 0.95);
  });
  if (!blob) {
    return null;
  }
  return URL.createObjectURL(blob);
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
  const imageCoordinates = imageCoordinatesForRegion(region);

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
      [IMG_SOURCE_A]: imageSourceFor(TRANSPARENT_IMAGE_URL, imageCoordinates),
      [IMG_SOURCE_B]: imageSourceFor(TRANSPARENT_IMAGE_URL, imageCoordinates),
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
        id: IMG_LAYER_A,
        type: "raster" as const,
        source: IMG_SOURCE_A,
        minzoom: overlayMinZoom,
        paint: {
          "raster-opacity": HIDDEN_OPACITY,
          "raster-resampling": resamplingMode,
          "raster-fade-duration": 0,
        },
      },
      {
        id: IMG_LAYER_B,
        type: "raster" as const,
        source: IMG_SOURCE_B,
        minzoom: overlayMinZoom,
        paint: {
          "raster-opacity": HIDDEN_OPACITY,
          "raster-resampling": resamplingMode,
          "raster-fade-duration": 0,
        },
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
  prefetchFrameImageUrls?: string[];
  crossfade?: boolean;
  onFrameSettled?: (tileUrl: string) => void;
  onTileReady?: (tileUrl: string) => void;
  onFrameImageReady?: (imageUrl: string) => void;
  onFrameImageError?: (imageUrl: string) => void;
  onZoomHint?: (show: boolean) => void;
  onRequestUrl?: (url: string) => void;
};

export function MapCanvas({
  tileUrl,
  frameImageUrl,
  region,
  opacity,
  mode: _mode,
  variable,
  model,
  preferFrameImages = true,
  scrubIsActive: _scrubIsActive = false,
  prefetchTileUrls = [],
  prefetchFrameImageUrls = [],
  crossfade: _crossfade = false,
  onFrameSettled,
  onTileReady,
  onFrameImageReady,
  onFrameImageError,
  onZoomHint,
  onRequestUrl,
}: MapCanvasProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const onRequestUrlRef = useRef(onRequestUrl);

  const activeOverlayModeRef = useRef<OverlayMode>("tile");
  const activeImageBufferRef = useRef<ActiveImageBuffer>("a");
  const activeImageUrlRef = useRef<string>("");

  const crossfadeRafRef = useRef<number | null>(null);
  const renderTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);

  const prefetchTileUrlsRef = useRef<string[]>(Array.from({ length: PREFETCH_TILE_BUFFER_COUNT }, () => ""));
  const loadedImageUrlsRef = useRef<Map<string, PreparedImage>>(new Map());
  const failedImageUrlsRef = useRef<Set<string>>(new Set());
  const inflightImageLoadsRef = useRef<Map<string, Promise<PreparedImage | null>>>(new Map());

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

  const setImageLayersForBuffer = useCallback(
    (map: maplibregl.Map, activeBuffer: ActiveImageBuffer, targetOpacity: number) => {
      setLayerOpacity(map, IMG_LAYER_A, activeBuffer === "a" ? targetOpacity : HIDDEN_OPACITY);
      setLayerOpacity(map, IMG_LAYER_B, activeBuffer === "b" ? targetOpacity : HIDDEN_OPACITY);
    },
    [setLayerOpacity]
  );

  const setActiveOverlayMode = useCallback(
    (map: maplibregl.Map, modeValue: OverlayMode, targetOpacity: number) => {
      activeOverlayModeRef.current = modeValue;
      setLayerOpacity(map, TILE_LAYER_ID, modeValue === "tile" ? targetOpacity : HIDDEN_OPACITY);
      if (modeValue === "image") {
        setImageLayersForBuffer(map, activeImageBufferRef.current, targetOpacity);
      } else {
        setLayerOpacity(map, IMG_LAYER_A, HIDDEN_OPACITY);
        setLayerOpacity(map, IMG_LAYER_B, HIDDEN_OPACITY);
      }
    },
    [setLayerOpacity, setImageLayersForBuffer]
  );

  const touchLoadedImage = useCallback((url: string, entry?: PreparedImage): PreparedImage | null => {
    const cache = loadedImageUrlsRef.current;
    const candidate = entry ?? cache.get(url);
    if (!candidate) {
      return null;
    }
    cache.delete(url);
    cache.set(url, candidate);

    while (cache.size > IMAGE_CACHE_MAX_ENTRIES) {
      const oldest = cache.keys().next().value as string | undefined;
      if (!oldest) {
        break;
      }
      const evicted = cache.get(oldest);
      if (evicted?.revokeUrl) {
        URL.revokeObjectURL(evicted.revokeUrl);
      }
      cache.delete(oldest);
    }
    return candidate;
  }, []);

  const preloadImageUrl = useCallback(
    async (url: string): Promise<PreparedImage | null> => {
      const normalizedUrl = url.trim();
      if (!normalizedUrl) {
        return null;
      }

      const cached = loadedImageUrlsRef.current.get(normalizedUrl);
      if (cached) {
        touchLoadedImage(normalizedUrl, cached);
        onFrameImageReady?.(normalizedUrl);
        return cached;
      }

      if (failedImageUrlsRef.current.has(normalizedUrl)) {
        return null;
      }

      const inflight = inflightImageLoadsRef.current.get(normalizedUrl);
      if (inflight) {
        return inflight;
      }

      const promise = new Promise<PreparedImage | null>((resolve) => {
        const image = new Image();
        image.crossOrigin = "anonymous";
        image.decoding = "async";

        const cleanup = () => {
          image.onload = null;
          image.onerror = null;
          inflightImageLoadsRef.current.delete(normalizedUrl);
        };

        image.onload = () => {
          void (async () => {
            const width = Math.max(1, image.naturalWidth || image.width || 1);
            const height = Math.max(1, image.naturalHeight || image.height || 1);
            const needsPot = !isPowerOfTwo(width) || !isPowerOfTwo(height);
            const potBlobUrl = await createPotImageBlobUrl(image);
            cleanup();
            if (needsPot && !potBlobUrl) {
              failedImageUrlsRef.current.add(normalizedUrl);
              onFrameImageError?.(normalizedUrl);
              resolve(null);
              return;
            }
            failedImageUrlsRef.current.delete(normalizedUrl);
            const prepared: PreparedImage = {
              mapUrl: potBlobUrl || normalizedUrl,
              revokeUrl: potBlobUrl || undefined,
            };
            const previous = loadedImageUrlsRef.current.get(normalizedUrl);
            if (previous?.revokeUrl && previous.revokeUrl !== prepared.revokeUrl) {
              URL.revokeObjectURL(previous.revokeUrl);
            }
            touchLoadedImage(normalizedUrl, prepared);
            onFrameImageReady?.(normalizedUrl);
            resolve(prepared);
          })();
        };

        image.onerror = () => {
          cleanup();
          failedImageUrlsRef.current.add(normalizedUrl);
          onFrameImageError?.(normalizedUrl);
          resolve(null);
        };

        image.src = normalizedUrl;
      });

      inflightImageLoadsRef.current.set(normalizedUrl, promise);
      return promise;
    },
    [onFrameImageReady, onFrameImageError, touchLoadedImage]
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

  const waitForImageSourceSettled = useCallback(
    (map: maplibregl.Map, sourceId: string, token: number): Promise<boolean> => {
      return new Promise((resolve) => {
        let done = false;
        let timeoutId: number | null = null;

        const cleanup = () => {
          map.off("sourcedata", onSourceData);
          if (timeoutId !== null) {
            window.clearTimeout(timeoutId);
            timeoutId = null;
          }
        };

        const finish = (ok: boolean) => {
          if (done) return;
          done = true;
          cleanup();
          resolve(ok && token === renderTokenRef.current);
        };

        const onSourceData = (event: maplibregl.MapSourceDataEvent) => {
          if (event.sourceId !== sourceId) {
            return;
          }
          if (map.isSourceLoaded(sourceId)) {
            window.requestAnimationFrame(() => finish(true));
          }
        };

        if (token !== renderTokenRef.current) {
          finish(false);
          return;
        }

        if (map.isSourceLoaded(sourceId)) {
          window.requestAnimationFrame(() => finish(true));
          return;
        }

        map.on("sourcedata", onSourceData);
        timeoutId = window.setTimeout(() => {
          finish(map.isSourceLoaded(sourceId));
        }, IMAGE_SOURCE_SETTLE_TIMEOUT_MS);
      });
    },
    []
  );

  const runImageCrossfade = useCallback(
    (map: maplibregl.Map, fromBuffer: ActiveImageBuffer, toBuffer: ActiveImageBuffer, targetOpacity: number) => {
      if (crossfadeRafRef.current !== null) {
        window.cancelAnimationFrame(crossfadeRafRef.current);
        crossfadeRafRef.current = null;
      }

      if (fromBuffer === toBuffer) {
        activeImageBufferRef.current = toBuffer;
        setImageLayersForBuffer(map, toBuffer, targetOpacity);
        setLayerOpacity(map, TILE_LAYER_ID, HIDDEN_OPACITY);
        activeOverlayModeRef.current = "image";
        return;
      }

      const fromLayer = fromBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
      const toLayer = toBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
      const startedAt = performance.now();

      const tick = (now: number) => {
        const progress = Math.min(1, (now - startedAt) / IMAGE_CROSSFADE_DURATION_MS);
        const fromOpacity = targetOpacity * (1 - progress) + HIDDEN_OPACITY * progress;
        const toOpacity = HIDDEN_OPACITY * (1 - progress) + targetOpacity * progress;

        setLayerOpacity(map, fromLayer, fromOpacity);
        setLayerOpacity(map, toLayer, toOpacity);
        setLayerOpacity(map, TILE_LAYER_ID, HIDDEN_OPACITY);

        if (progress >= 1) {
          activeImageBufferRef.current = toBuffer;
          activeOverlayModeRef.current = "image";
          setLayerOpacity(map, fromLayer, HIDDEN_OPACITY);
          setLayerOpacity(map, toLayer, targetOpacity);
          crossfadeRafRef.current = null;
          return;
        }

        crossfadeRafRef.current = window.requestAnimationFrame(tick);
      };

      crossfadeRafRef.current = window.requestAnimationFrame(tick);
    },
    [setImageLayersForBuffer, setLayerOpacity]
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
      setIsLoaded(true);
    });

    mapRef.current = map;
  }, [tileUrl, opacity, variable, model, region, view.center, view.zoom]);

  useEffect(() => {
    return () => {
      if (crossfadeRafRef.current !== null) {
        window.cancelAnimationFrame(crossfadeRafRef.current);
        crossfadeRafRef.current = null;
      }

      prefetchTokenRef.current += 1;
      renderTokenRef.current += 1;

      const map = mapRef.current;
      if (map) {
        map.remove();
        mapRef.current = null;
      }

      setIsLoaded(false);
      for (const entry of loadedImageUrlsRef.current.values()) {
        if (entry.revokeUrl) {
          URL.revokeObjectURL(entry.revokeUrl);
        }
      }
      loadedImageUrlsRef.current.clear();
      failedImageUrlsRef.current.clear();
      inflightImageLoadsRef.current.clear();
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

    const sourceA = map.getSource(IMG_SOURCE_A) as MutableImageSource | undefined;
    sourceA?.setCoordinates?.(imageCoordinates);
    const sourceB = map.getSource(IMG_SOURCE_B) as MutableImageSource | undefined;
    sourceB?.setCoordinates?.(imageCoordinates);

    if (map.getLayer(TILE_LAYER_ID)) {
      map.setPaintProperty(TILE_LAYER_ID, "raster-resampling", resamplingMode);
      map.setLayerZoomRange(TILE_LAYER_ID, overlayMinZoom, 24);
    }

    if (map.getLayer(IMG_LAYER_A)) {
      map.setPaintProperty(IMG_LAYER_A, "raster-resampling", resamplingMode);
      map.setLayerZoomRange(IMG_LAYER_A, overlayMinZoom, 24);
    }

    if (map.getLayer(IMG_LAYER_B)) {
      map.setPaintProperty(IMG_LAYER_B, "raster-resampling", resamplingMode);
      map.setLayerZoomRange(IMG_LAYER_B, overlayMinZoom, 24);
    }

    for (let idx = 1; idx <= PREFETCH_TILE_BUFFER_COUNT; idx += 1) {
      const layer = prefetchLayerId(idx);
      if (!map.getLayer(layer)) continue;
      map.setPaintProperty(layer, "raster-resampling", resamplingMode);
      map.setLayerZoomRange(layer, overlayMinZoom, 24);
    }
  }, [isLoaded, imageCoordinates, overlayMinZoom, resamplingMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !tileUrl) {
      return;
    }

    const token = ++renderTokenRef.current;
    let settledCleanup: (() => void) | undefined;

    const fallbackToTile = () => {
      if (token !== renderTokenRef.current) {
        return;
      }
      const tileSource = map.getSource(TILE_SOURCE_ID);
      if (!setOverlaySourceUrl(tileSource, tileUrl)) {
        return;
      }
      activeImageUrlRef.current = "";
      setActiveOverlayMode(map, "tile", opacity);
      onTileReady?.(tileUrl);
      settledCleanup = notifyTileSettled(map, tileUrl, token);
    };

    const targetImageUrl = frameImageUrl?.trim() || "";
    const shouldUseImageMode = preferFrameImages && targetImageUrl.length > 0;

    if (!shouldUseImageMode) {
      fallbackToTile();
      return () => {
        settledCleanup?.();
      };
    }

    if (activeOverlayModeRef.current === "image" && activeImageUrlRef.current === targetImageUrl) {
      setActiveOverlayMode(map, "image", opacity);
      onTileReady?.(tileUrl);
      onFrameSettled?.(tileUrl);
      return () => {
        settledCleanup?.();
      };
    }

    void preloadImageUrl(targetImageUrl)
      .then(async (prepared) => {
        if (token !== renderTokenRef.current) {
          return;
        }
        if (!prepared) {
          fallbackToTile();
          return;
        }

        const nextBuffer: ActiveImageBuffer = activeImageBufferRef.current === "a" ? "b" : "a";
        const sourceId = nextBuffer === "a" ? IMG_SOURCE_A : IMG_SOURCE_B;
        const imageSource = map.getSource(sourceId);

        if (!setImageSourceUrl(imageSource, prepared.mapUrl, imageCoordinates)) {
          fallbackToTile();
          return;
        }
        const sourceSettled = await waitForImageSourceSettled(map, sourceId, token);
        if (token !== renderTokenRef.current) {
          return;
        }
        if (!sourceSettled) {
          failedImageUrlsRef.current.add(targetImageUrl);
          onFrameImageError?.(targetImageUrl);
          fallbackToTile();
          return;
        }

        if (activeOverlayModeRef.current === "image" && activeImageUrlRef.current) {
          runImageCrossfade(map, activeImageBufferRef.current, nextBuffer, opacity);
        } else {
          activeImageBufferRef.current = nextBuffer;
          setImageLayersForBuffer(map, nextBuffer, opacity);
          setLayerOpacity(map, TILE_LAYER_ID, HIDDEN_OPACITY);
          activeOverlayModeRef.current = "image";
        }

        activeImageUrlRef.current = targetImageUrl;
        onTileReady?.(tileUrl);
        onFrameSettled?.(tileUrl);
      })
      .catch(() => {
        if (token !== renderTokenRef.current) {
          return;
        }
        fallbackToTile();
      });

    return () => {
      settledCleanup?.();
    };
  }, [
    frameImageUrl,
    imageCoordinates,
    isLoaded,
    notifyTileSettled,
    onFrameImageError,
    onFrameSettled,
    onTileReady,
    opacity,
    preferFrameImages,
    preloadImageUrl,
    runImageCrossfade,
    setActiveOverlayMode,
    setImageLayersForBuffer,
    setLayerOpacity,
    tileUrl,
    waitForImageSourceSettled,
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

    const run = async () => {
      for (const url of uniqueQueue) {
        if (cancelled || token !== prefetchTokenRef.current) {
          return;
        }
        await preloadImageUrl(url);
        if (cancelled || token !== prefetchTokenRef.current) {
          return;
        }
        await new Promise<void>((resolve) => {
          window.setTimeout(() => resolve(), IMAGE_PREFETCH_THROTTLE_MS);
        });
      }
    };

    void run();

    return () => {
      cancelled = true;
      if (prefetchTokenRef.current === token) {
        prefetchTokenRef.current += 1;
      }
    };
  }, [prefetchFrameImageUrls, preloadImageUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    setLayerOpacity(map, TILE_LAYER_ID, HIDDEN_OPACITY);
    setLayerOpacity(map, IMG_LAYER_A, HIDDEN_OPACITY);
    setLayerOpacity(map, IMG_LAYER_B, HIDDEN_OPACITY);

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
