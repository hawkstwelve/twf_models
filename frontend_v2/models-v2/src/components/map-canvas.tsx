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

const SCRUB_SWAP_TIMEOUT_MS = 350;
const AUTOPLAY_SWAP_TIMEOUT_MS = 1500;
const SETTLE_TIMEOUT_MS = 1200;
const CONTINUOUS_CROSSFADE_MS = 120;
const MICRO_CROSSFADE_MS = 60;
const PREFETCH_TILE_BUFFER_COUNT = 4;

const IMAGE_PREFETCH_LOOKAHEAD = 16;
const IMAGE_PREFETCH_THROTTLE_MS = 90;
const IMAGE_CACHE_MAX_ENTRIES = 36;

const HIDDEN_OPACITY = 0.001;
const EMPTY_IMAGE_DATA_URL = "data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==";

type OverlayBuffer = "a" | "b";
type OverlayMode = "tile" | "image";
type PlaybackMode = "autoplay" | "scrub";
type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];

type MutableRasterSource = maplibregl.RasterTileSource & {
  setTiles?: (tiles: string[]) => maplibregl.RasterTileSource;
  setUrl?: (url: string) => maplibregl.RasterTileSource;
};

type MutableImageSource = maplibregl.ImageSource & {
  updateImage?: (options: { url: string; coordinates: ImageCoordinates }) => maplibregl.ImageSource;
};

type ImageCacheEntry = {
  status: "ready" | "error";
  image?: HTMLImageElement;
};

export type PrefetchFrameImage = {
  tileUrl: string;
  frameImageUrl?: string;
};

function tileSourceId(buffer: OverlayBuffer): string {
  return `twf-overlay-${buffer}`;
}

function tileLayerId(buffer: OverlayBuffer): string {
  return `twf-overlay-${buffer}`;
}

function imageSourceId(buffer: OverlayBuffer): string {
  return `twf-img-${buffer}`;
}

function imageLayerId(buffer: OverlayBuffer): string {
  return `twf-img-${buffer}`;
}

function overlayLayerId(mode: OverlayMode, buffer: OverlayBuffer): string {
  return mode === "image" ? imageLayerId(buffer) : tileLayerId(buffer);
}

function otherBuffer(buffer: OverlayBuffer): OverlayBuffer {
  return buffer === "a" ? "b" : "a";
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
  if (!imageSource || typeof imageSource.updateImage !== "function") {
    return false;
  }
  imageSource.updateImage({ url, coordinates });
  return true;
}

function styleFor(
  overlayUrl: string,
  initialImageUrl: string,
  opacity: number,
  variable?: string,
  model?: string,
  region?: string
): StyleSpecification {
  const resamplingMode = getResamplingMode(variable);
  const overlayBounds = (region && REGION_BOUNDS[region]) || REGION_BOUNDS.pnw;
  const imageCoordinates = imageCoordinatesForRegion(region);
  const overlayMinZoom = model === "gfs" ? 6 : 3;

  const prefetchSources = Object.fromEntries(
    Array.from({ length: PREFETCH_TILE_BUFFER_COUNT }, (_, idx) => [
      prefetchSourceId(idx + 1),
      overlaySourceFor(overlayUrl, overlayBounds),
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
      [tileSourceId("a")]: overlaySourceFor(overlayUrl, overlayBounds),
      [tileSourceId("b")]: overlaySourceFor(overlayUrl, overlayBounds),
      ...prefetchSources,
      [imageSourceId("a")]: imageSourceFor(initialImageUrl, imageCoordinates),
      [imageSourceId("b")]: imageSourceFor(initialImageUrl, imageCoordinates),
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
        id: tileLayerId("a"),
        type: "raster" as const,
        source: tileSourceId("a"),
        minzoom: overlayMinZoom,
        paint: {
          "raster-opacity": opacity,
          "raster-resampling": resamplingMode,
          "raster-fade-duration": 0,
        },
      },
      {
        id: tileLayerId("b"),
        type: "raster" as const,
        source: tileSourceId("b"),
        minzoom: overlayMinZoom,
        paint: {
          "raster-opacity": HIDDEN_OPACITY,
          "raster-resampling": resamplingMode,
          "raster-fade-duration": 0,
        },
      },
      ...prefetchLayers,
      {
        id: imageLayerId("a"),
        type: "raster" as const,
        source: imageSourceId("a"),
        minzoom: overlayMinZoom,
        paint: {
          "raster-opacity": HIDDEN_OPACITY,
          "raster-resampling": resamplingMode,
          "raster-fade-duration": 0,
        },
      },
      {
        id: imageLayerId("b"),
        type: "raster" as const,
        source: imageSourceId("b"),
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
  crossfade = false,
  onFrameSettled,
  onTileReady,
  onZoomHint,
  onRequestUrl,
}: MapCanvasProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const activeBufferRef = useRef<OverlayBuffer>("a");
  const activeModeRef = useRef<OverlayMode>("tile");
  const activeTileUrlRef = useRef(tileUrl);
  const activeFrameImageUrlRef = useRef<string | null>(null);
  const imageSourceUrlsRef = useRef<Record<OverlayBuffer, string>>({
    a: EMPTY_IMAGE_DATA_URL,
    b: EMPTY_IMAGE_DATA_URL,
  });

  const swapTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);
  const prefetchTileUrlsRef = useRef<string[]>(Array.from({ length: PREFETCH_TILE_BUFFER_COUNT }, () => ""));

  const fadeTokenRef = useRef(0);
  const fadeRafRef = useRef<number | null>(null);
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

  const imageCoordinates = useMemo(() => imageCoordinatesForRegion(region), [region]);

  const setLayerOpacity = useCallback((map: maplibregl.Map, id: string, value: number) => {
    if (!map.getLayer(id)) {
      return;
    }
    map.setPaintProperty(id, "raster-opacity", value);
  }, []);

  const notifySettled = useCallback(
    (map: maplibregl.Map, source: string, url: string) => {
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
        done = true;
        cleanup();
        onTileReady?.(url);
        onFrameSettled?.(url);
      };

      const onSourceData = (event: maplibregl.MapSourceDataEvent) => {
        if (event.sourceId !== source) {
          return;
        }
        if (map.isSourceLoaded(source)) {
          window.requestAnimationFrame(() => fire());
        }
      };

      if (map.isSourceLoaded(source)) {
        window.requestAnimationFrame(() => fire());
        return () => {
          done = true;
          cleanup();
        };
      }

      map.on("sourcedata", onSourceData);
      timeoutId = window.setTimeout(() => {
        fire();
      }, SETTLE_TIMEOUT_MS);

      return () => {
        done = true;
        cleanup();
      };
    },
    [onTileReady, onFrameSettled]
  );

  const cancelCrossfade = useCallback(() => {
    fadeTokenRef.current += 1;
    if (fadeRafRef.current !== null) {
      window.cancelAnimationFrame(fadeRafRef.current);
      fadeRafRef.current = null;
    }
  }, []);

  const runLayerCrossfade = useCallback(
    (
      map: maplibregl.Map,
      fromLayer: string,
      toLayer: string,
      targetOpacity: number,
      durationMs: number,
      swapToken: number,
      onComplete?: () => void
    ) => {
      cancelCrossfade();

      if (fromLayer === toLayer) {
        setLayerOpacity(map, toLayer, targetOpacity);
        onComplete?.();
        return;
      }

      const fadeToken = ++fadeTokenRef.current;
      const started = performance.now();

      const tick = (now: number) => {
        if (fadeToken !== fadeTokenRef.current || swapToken !== swapTokenRef.current) {
          return;
        }

        const progress = Math.min(1, (now - started) / Math.max(1, durationMs));
        const fromOpacity = targetOpacity * (1 - progress);
        const toOpacity = targetOpacity * progress;

        setLayerOpacity(map, fromLayer, Math.max(HIDDEN_OPACITY, fromOpacity));
        setLayerOpacity(map, toLayer, Math.max(HIDDEN_OPACITY, toOpacity));

        if (progress < 1) {
          fadeRafRef.current = window.requestAnimationFrame(tick);
          return;
        }

        setLayerOpacity(map, fromLayer, HIDDEN_OPACITY);
        setLayerOpacity(map, toLayer, targetOpacity);
        fadeRafRef.current = null;
        onComplete?.();
      };

      setLayerOpacity(map, fromLayer, targetOpacity);
      setLayerOpacity(map, toLayer, HIDDEN_OPACITY);
      fadeRafRef.current = window.requestAnimationFrame(tick);
    },
    [cancelCrossfade, setLayerOpacity]
  );

  const waitForSourceReady = useCallback(
    (
      map: maplibregl.Map,
      source: string,
      modeValue: PlaybackMode,
      onReady: () => void,
      onTimeout?: () => void
    ) => {
      const timeoutMs = modeValue === "autoplay" ? AUTOPLAY_SWAP_TIMEOUT_MS : SCRUB_SWAP_TIMEOUT_MS;
      let done = false;
      let timeoutId: number | null = null;
      let seenLoadedState = map.isSourceLoaded(source);
      let scrubReadyQueued = false;

      const cleanup = () => {
        map.off("sourcedata", onSourceData);
        map.off("idle", onIdle);
        if (timeoutId !== null) {
          window.clearTimeout(timeoutId);
          timeoutId = null;
        }
      };

      const finishReady = () => {
        if (done) return;
        done = true;
        cleanup();
        onReady();
      };

      const finishTimeout = () => {
        if (done) return;
        done = true;
        cleanup();
        onTimeout?.();
      };

      const finishReadyAfterRender = () => {
        if (done) {
          return;
        }
        window.requestAnimationFrame(() => {
          window.requestAnimationFrame(() => {
            if (!done) {
              finishReady();
            }
          });
        });
      };

      const onSourceData = (event: maplibregl.MapSourceDataEvent) => {
        if (event.sourceId !== source) {
          return;
        }
        if (modeValue === "autoplay" && map.isSourceLoaded(source)) {
          seenLoadedState = true;
        }
        if (modeValue === "scrub" && map.isSourceLoaded(source) && !scrubReadyQueued) {
          scrubReadyQueued = true;
          finishReadyAfterRender();
        }
      };

      const onIdle = () => {
        if (modeValue !== "autoplay") {
          return;
        }
        if (!seenLoadedState) {
          return;
        }
        if (!map.isSourceLoaded(source)) {
          return;
        }
        finishReady();
      };

      map.on("sourcedata", onSourceData);
      if (modeValue === "autoplay") {
        map.on("idle", onIdle);
      } else if (seenLoadedState && !scrubReadyQueued) {
        scrubReadyQueued = true;
        finishReadyAfterRender();
      }

      timeoutId = window.setTimeout(() => finishTimeout(), timeoutMs);

      return () => {
        done = true;
        cleanup();
      };
    },
    []
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
      if (evicted?.image) {
        evicted.image.onload = null;
        evicted.image.onerror = null;
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

        const finish = (ok: boolean) => {
          if (done) return;
          done = true;
          img.onload = null;
          img.onerror = null;
          imagePendingRef.current.delete(normalizedUrl);

          if (ok) {
            unavailableFrameImageUrlsRef.current.delete(normalizedUrl);
            touchImageCache(normalizedUrl, { status: "ready", image: img });
          } else {
            unavailableFrameImageUrlsRef.current.add(normalizedUrl);
            touchImageCache(normalizedUrl, { status: "error" });
          }
          resolve(ok);
        };

        img.onload = () => finish(true);
        img.onerror = () => finish(false);
        img.src = normalizedUrl;
      });

      imagePendingRef.current.set(normalizedUrl, promise);
      return promise;
    },
    [touchImageCache]
  );

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }
    if (!tileUrl) {
      return;
    }
    ensurePmtilesProtocol();

    const initialFrameImageUrl = EMPTY_IMAGE_DATA_URL;
    imageSourceUrlsRef.current = {
      a: initialFrameImageUrl,
      b: initialFrameImageUrl,
    };
    activeBufferRef.current = "a";
    activeModeRef.current = "tile";
    activeTileUrlRef.current = tileUrl;
    activeFrameImageUrlRef.current = null;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: styleFor(tileUrl, initialFrameImageUrl, opacity, variable, model, region),
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
      cancelCrossfade();
      const map = mapRef.current;
      if (map) {
        map.remove();
        mapRef.current = null;
      }
      setIsLoaded(false);
    };
  }, [cancelCrossfade]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !onZoomHint) {
      return;
    }

    const lastHintStateRef = { current: false };

    const checkZoom = () => {
      const zoom = map.getZoom();
      const shouldShow = model === "gfs" && zoom >= 7;
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

    (["a", "b"] as OverlayBuffer[]).forEach((buffer) => {
      const nextUrl = imageSourceUrlsRef.current[buffer] || EMPTY_IMAGE_DATA_URL;
      const source = map.getSource(imageSourceId(buffer));
      setImageSourceUrl(source, nextUrl, imageCoordinates);
    });
  }, [isLoaded, imageCoordinates]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !tileUrl) {
      return;
    }

    let settledCleanup: (() => void) | undefined;
    let readyCleanup: (() => void) | undefined;
    let cancelled = false;

    const token = ++swapTokenRef.current;
    const previousBuffer = activeBufferRef.current;
    const nextBuffer = otherBuffer(previousBuffer);
    const previousMode = activeModeRef.current;
    const normalizedFrameImageUrl = frameImageUrl?.trim() || "";
    const canTryFrameImage =
      preferFrameImages &&
      normalizedFrameImageUrl.length > 0 &&
      !unavailableFrameImageUrlsRef.current.has(normalizedFrameImageUrl);
    const desiredMode: OverlayMode = canTryFrameImage ? "image" : "tile";

    const alreadyShowingDesiredFrame =
      activeTileUrlRef.current === tileUrl &&
      previousMode === desiredMode &&
      (desiredMode === "tile" || activeFrameImageUrlRef.current === normalizedFrameImageUrl);

    if (alreadyShowingDesiredFrame) {
      if (desiredMode === "image") {
        onTileReady?.(tileUrl);
        onFrameSettled?.(tileUrl);
        return;
      }

      const source = tileSourceId(activeBufferRef.current);
      const readyExisting = waitForSourceReady(
        map,
        source,
        mode,
        () => {
          settledCleanup = notifySettled(map, source, tileUrl);
        },
        () => {
          if (mode === "autoplay") {
            onTileReady?.(tileUrl);
            onFrameSettled?.(tileUrl);
          }
        }
      );

      return () => {
        readyExisting?.();
        settledCleanup?.();
      };
    }

    const finalizeSwap = (nextMode: OverlayMode, skipSettleNotify = false) => {
      if (cancelled || token !== swapTokenRef.current) {
        return;
      }

      const fromLayer = overlayLayerId(previousMode, previousBuffer);
      const toLayer = overlayLayerId(nextMode, nextBuffer);

      activeBufferRef.current = nextBuffer;
      activeModeRef.current = nextMode;
      activeTileUrlRef.current = tileUrl;
      activeFrameImageUrlRef.current = nextMode === "image" ? normalizedFrameImageUrl : null;

      const durationMs = crossfade ? CONTINUOUS_CROSSFADE_MS : MICRO_CROSSFADE_MS;
      runLayerCrossfade(map, fromLayer, toLayer, opacity, durationMs, token, () => {
        if (cancelled || token !== swapTokenRef.current) {
          return;
        }

        if (nextMode === "image") {
          onTileReady?.(tileUrl);
          onFrameSettled?.(tileUrl);
          return;
        }

        if (!skipSettleNotify) {
          settledCleanup = notifySettled(map, tileSourceId(nextBuffer), tileUrl);
        }
      });
    };

    const swapToTile = () => {
      const nextSource = map.getSource(tileSourceId(nextBuffer));
      if (!setOverlaySourceUrl(nextSource, tileUrl)) {
        return;
      }

      readyCleanup = waitForSourceReady(
        map,
        tileSourceId(nextBuffer),
        mode,
        () => {
          finalizeSwap("tile");
        },
        () => {
          if (token !== swapTokenRef.current || cancelled) {
            return;
          }
          if (mode === "autoplay") {
            onTileReady?.(tileUrl);
            onFrameSettled?.(tileUrl);
            finalizeSwap("tile", true);
            return;
          }
          finalizeSwap("tile", true);
        }
      );
    };

    if (canTryFrameImage && normalizedFrameImageUrl) {
      preloadFrameImage(normalizedFrameImageUrl)
        .then((ready) => {
          if (token !== swapTokenRef.current || cancelled) {
            return;
          }
          if (!ready) {
            swapToTile();
            return;
          }

          const nextImageSource = map.getSource(imageSourceId(nextBuffer));
          const updated = setImageSourceUrl(nextImageSource, normalizedFrameImageUrl, imageCoordinates);
          if (!updated) {
            swapToTile();
            return;
          }

          imageSourceUrlsRef.current[nextBuffer] = normalizedFrameImageUrl;
          window.requestAnimationFrame(() => finalizeSwap("image", true));
        })
        .catch(() => {
          if (token !== swapTokenRef.current || cancelled) {
            return;
          }
          swapToTile();
        });
    } else {
      swapToTile();
    }

    return () => {
      cancelled = true;
      readyCleanup?.();
      settledCleanup?.();
    };
  }, [
    tileUrl,
    frameImageUrl,
    preferFrameImages,
    imageCoordinates,
    isLoaded,
    mode,
    opacity,
    crossfade,
    runLayerCrossfade,
    notifySettled,
    waitForSourceReady,
    preloadFrameImage,
    onTileReady,
    onFrameSettled,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    const token = ++prefetchTokenRef.current;
    const urls = Array.from({ length: PREFETCH_TILE_BUFFER_COUNT }, (_, idx) => prefetchTileUrls[idx] ?? "");
    const cleanups: Array<() => void> = [];

    urls.forEach((url, idx) => {
      const source = map.getSource(prefetchSourceId(idx + 1));
      if (!source) {
        return;
      }

      if (!url) {
        prefetchTileUrlsRef.current[idx] = "";
        return;
      }

      if (prefetchTileUrlsRef.current[idx] === url) {
        return;
      }

      prefetchTileUrlsRef.current[idx] = url;
      if (!setOverlaySourceUrl(source, url)) {
        return;
      }

      const cleanup = waitForSourceReady(
        map,
        prefetchSourceId(idx + 1),
        "scrub",
        () => {
          if (token !== prefetchTokenRef.current) {
            return;
          }
          if (prefetchTileUrlsRef.current[idx] !== url) {
            return;
          }
          onTileReady?.(url);
        },
        () => {
          if (token !== prefetchTokenRef.current) {
            return;
          }
          if (prefetchTileUrlsRef.current[idx] !== url) {
            return;
          }
          onTileReady?.(url);
        }
      );

      if (cleanup) {
        cleanups.push(cleanup);
      }
    });

    return () => {
      cleanups.forEach((cleanup) => cleanup());
    };
  }, [prefetchTileUrls, isLoaded, waitForSourceReady, onTileReady]);

  useEffect(() => {
    if (prefetchFrameImages.length === 0) {
      return;
    }

    const queue = prefetchFrameImages
      .slice(0, IMAGE_PREFETCH_LOOKAHEAD)
      .filter((entry) => entry.frameImageUrl && entry.frameImageUrl.trim())
      .filter((entry) => !unavailableFrameImageUrlsRef.current.has(entry.frameImageUrl!.trim()));

    if (queue.length === 0) {
      return;
    }

    let cancelled = false;

    const run = async () => {
      for (const entry of queue) {
        if (cancelled) {
          break;
        }

        const url = entry.frameImageUrl?.trim();
        if (!url) {
          continue;
        }

        const ready = await preloadFrameImage(url);
        if (cancelled) {
          break;
        }

        if (ready) {
          onTileReady?.(entry.tileUrl);
        }

        await new Promise<void>((resolve) => {
          window.setTimeout(() => resolve(), IMAGE_PREFETCH_THROTTLE_MS);
        });
      }
    };

    run();

    return () => {
      cancelled = true;
    };
  }, [prefetchFrameImages, preloadFrameImage, onTileReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    cancelCrossfade();

    setLayerOpacity(map, tileLayerId("a"), HIDDEN_OPACITY);
    setLayerOpacity(map, tileLayerId("b"), HIDDEN_OPACITY);
    setLayerOpacity(map, imageLayerId("a"), HIDDEN_OPACITY);
    setLayerOpacity(map, imageLayerId("b"), HIDDEN_OPACITY);
    for (let idx = 1; idx <= PREFETCH_TILE_BUFFER_COUNT; idx += 1) {
      setLayerOpacity(map, prefetchLayerId(idx), HIDDEN_OPACITY);
    }

    const activeLayer = overlayLayerId(activeModeRef.current, activeBufferRef.current);
    setLayerOpacity(map, activeLayer, opacity);
  }, [opacity, isLoaded, cancelCrossfade, setLayerOpacity]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }
    map.easeTo({ center: view.center, zoom: view.zoom, duration: 600 });
  }, [view, isLoaded]);

  return <div ref={mapContainerRef} className="absolute inset-0" aria-label="Weather map" />;
}
