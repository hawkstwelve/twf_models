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

const IMAGE_SOURCE_SETTLE_TIMEOUT_MS = 1500;
const IMAGE_CACHE_MAX_ENTRIES = 40;
const IMAGE_CROSSFADE_DURATION_MS = 60;
const IMAGE_PREFETCH_THROTTLE_MS = 24;
const MAX_IMAGE_TEXTURE_SIZE = 4096;
const HIDDEN_OPACITY = 0;
const TRANSPARENT_IMAGE_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVQImWP8z/D/PwMDAwMjIAMAFAIB7l9d0QAAAABJRU5ErkJggg==";

const IMG_SOURCE_A = "twf-img-a";
const IMG_SOURCE_B = "twf-img-b";
const IMG_LAYER_A = "twf-img-a";
const IMG_LAYER_B = "twf-img-b";

type ActiveImageBuffer = "a" | "b";
type PlaybackMode = "autoplay" | "scrub";
type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];

type MutableImageSource = maplibregl.ImageSource & {
  updateImage?: (options: { url: string; coordinates: ImageCoordinates }) => maplibregl.ImageSource;
  setCoordinates?: (coordinates: ImageCoordinates) => void;
};

type PreparedImage = {
  mapUrl: string;
  revokeUrl?: string;
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

function imageSourceFor(url: string, coordinates: ImageCoordinates) {
  return {
    type: "image",
    url,
    coordinates,
  };
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

function setLayerVisibility(map: maplibregl.Map, id: string, visible: boolean): void {
  if (!map.getLayer(id)) {
    return;
  }
  map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
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

function isBlobUrl(url?: string): url is string {
  return typeof url === "string" && url.startsWith("blob:");
}

async function createPotImageBlobUrl(image: HTMLImageElement): Promise<string | null> {
  const width = Math.max(1, image.naturalWidth || image.width || 1);
  const height = Math.max(1, image.naturalHeight || image.height || 1);
  if (isPowerOfTwo(width) && isPowerOfTwo(height)) {
    return null;
  }

  const potWidth = nextPowerOfTwo(width);
  const potHeight = nextPowerOfTwo(height);
  if (potWidth > MAX_IMAGE_TEXTURE_SIZE || potHeight > MAX_IMAGE_TEXTURE_SIZE) {
    return null;
  }

  const canvas = document.createElement("canvas");
  canvas.width = potWidth;
  canvas.height = potHeight;
  const context = canvas.getContext("2d", { alpha: true });
  if (!context) {
    return null;
  }

  context.imageSmoothingEnabled = false;
  context.clearRect(0, 0, potWidth, potHeight);
  // Keep original pixel dimensions; pad remaining POT area with transparent pixels.
  context.drawImage(image, 0, 0, width, height);

  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob((nextBlob) => resolve(nextBlob), "image/webp", 0.95);
  });
  if (!blob) {
    return null;
  }
  return URL.createObjectURL(blob);
}

function styleFor(opacity: number, variable?: string, model?: string, region?: string): StyleSpecification {
  const resamplingMode = getResamplingMode(variable);
  const overlayMinZoom = model === "gfs" ? 6 : 3;
  const imageCoordinates = imageCoordinatesForRegion(region);

  return {
    version: 8,
    sources: {
      "twf-basemap": {
        type: "raster",
        tiles: CARTO_LIGHT_BASE_TILES,
        tileSize: 256,
        attribution: BASEMAP_ATTRIBUTION,
      },
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
        id: IMG_LAYER_A,
        type: "raster" as const,
        source: IMG_SOURCE_A,
        minzoom: overlayMinZoom,
        layout: {
          visibility: "none",
        },
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
        layout: {
          visibility: "none",
        },
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
  frameImageUrl?: string;
  region: string;
  opacity: number;
  mode: PlaybackMode;
  variable?: string;
  model?: string;
  scrubIsActive?: boolean;
  prefetchFrameImageUrls?: string[];
  crossfade?: boolean;
  onFrameSettled?: (imageUrl: string) => void;
  onFrameImageReady?: (imageUrl: string) => void;
  onFrameImageError?: (imageUrl: string) => void;
  onZoomHint?: (show: boolean) => void;
  onRequestUrl?: (url: string) => void;
};

export function MapCanvas({
  frameImageUrl,
  region,
  opacity,
  mode: _mode,
  variable,
  model,
  scrubIsActive: _scrubIsActive = false,
  prefetchFrameImageUrls = [],
  crossfade = false,
  onFrameSettled,
  onFrameImageReady,
  onFrameImageError,
  onZoomHint,
  onRequestUrl,
}: MapCanvasProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  const onRequestUrlRef = useRef(onRequestUrl);

  const activeImageBufferRef = useRef<ActiveImageBuffer>("a");
  const activeImageUrlRef = useRef<string>("");
  const assignedSourceMapUrlsRef = useRef<Record<ActiveImageBuffer, string>>({
    a: TRANSPARENT_IMAGE_URL,
    b: TRANSPARENT_IMAGE_URL,
  });

  const crossfadeRafRef = useRef<number | null>(null);
  const renderTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);

  const loadedImageUrlsRef = useRef<Map<string, PreparedImage>>(new Map());
  const failedImageUrlsRef = useRef<Set<string>>(new Set());
  const inflightImageLoadsRef = useRef<Map<string, Promise<PreparedImage | null>>>(new Map());
  const pendingBlobRevokesRef = useRef<Set<string>>(new Set());

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
      const showA = activeBuffer === "a";
      const showB = activeBuffer === "b";
      setLayerVisibility(map, IMG_LAYER_A, showA);
      setLayerVisibility(map, IMG_LAYER_B, showB);
      setLayerOpacity(map, IMG_LAYER_A, showA ? targetOpacity : HIDDEN_OPACITY);
      setLayerOpacity(map, IMG_LAYER_B, showB ? targetOpacity : HIDDEN_OPACITY);
    },
    [setLayerOpacity]
  );

  const hideImageLayers = useCallback(
    (map: maplibregl.Map) => {
      setLayerVisibility(map, IMG_LAYER_A, false);
      setLayerVisibility(map, IMG_LAYER_B, false);
      setLayerOpacity(map, IMG_LAYER_A, HIDDEN_OPACITY);
      setLayerOpacity(map, IMG_LAYER_B, HIDDEN_OPACITY);
    },
    [setLayerOpacity]
  );

  const revokeBlobUrlIfUnused = useCallback((url?: string) => {
    if (!isBlobUrl(url)) {
      return;
    }
    const activeSources = assignedSourceMapUrlsRef.current;
    if (activeSources.a === url || activeSources.b === url) {
      pendingBlobRevokesRef.current.add(url);
      return;
    }
    pendingBlobRevokesRef.current.delete(url);
    URL.revokeObjectURL(url);
  }, []);

  const flushPendingBlobRevokes = useCallback(() => {
    const pending = pendingBlobRevokesRef.current;
    if (pending.size === 0) {
      return;
    }
    const assigned = assignedSourceMapUrlsRef.current;
    for (const url of Array.from(pending)) {
      if (assigned.a === url || assigned.b === url) {
        continue;
      }
      pending.delete(url);
      URL.revokeObjectURL(url);
    }
  }, []);

  const assignSourceMapUrl = useCallback(
    (buffer: ActiveImageBuffer, nextUrl: string) => {
      const previousUrl = assignedSourceMapUrlsRef.current[buffer];
      assignedSourceMapUrlsRef.current[buffer] = nextUrl;
      if (previousUrl && previousUrl !== nextUrl) {
        revokeBlobUrlIfUnused(previousUrl);
      }
      flushPendingBlobRevokes();
    },
    [flushPendingBlobRevokes, revokeBlobUrlIfUnused]
  );

  const touchLoadedImage = useCallback(
    (url: string, entry?: PreparedImage): PreparedImage | null => {
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
        cache.delete(oldest);
        if (evicted?.revokeUrl) {
          revokeBlobUrlIfUnused(evicted.revokeUrl);
        }
      }

      flushPendingBlobRevokes();
      return candidate;
    },
    [flushPendingBlobRevokes, revokeBlobUrlIfUnused]
  );

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
            const potBlobUrl = needsPot ? await createPotImageBlobUrl(image) : null;
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
              revokeBlobUrlIfUnused(previous.revokeUrl);
            }

            touchLoadedImage(normalizedUrl, prepared);
            flushPendingBlobRevokes();
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
    [flushPendingBlobRevokes, onFrameImageError, onFrameImageReady, revokeBlobUrlIfUnused, touchLoadedImage]
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
        return;
      }

      const fromLayer = fromBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
      const toLayer = toBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
      const startedAt = performance.now();
      setLayerVisibility(map, fromLayer, true);
      setLayerVisibility(map, toLayer, true);

      const tick = (now: number) => {
        const progress = Math.min(1, (now - startedAt) / IMAGE_CROSSFADE_DURATION_MS);
        const fromOpacity = targetOpacity * (1 - progress) + HIDDEN_OPACITY * progress;
        const toOpacity = HIDDEN_OPACITY * (1 - progress) + targetOpacity * progress;

        setLayerOpacity(map, fromLayer, fromOpacity);
        setLayerOpacity(map, toLayer, toOpacity);

        if (progress >= 1) {
          activeImageBufferRef.current = toBuffer;
          setLayerVisibility(map, fromLayer, false);
          setLayerVisibility(map, toLayer, true);
          setLayerOpacity(map, fromLayer, HIDDEN_OPACITY);
          setLayerOpacity(map, toLayer, targetOpacity);
          crossfadeRafRef.current = null;
          flushPendingBlobRevokes();
          return;
        }

        crossfadeRafRef.current = window.requestAnimationFrame(tick);
      };

      crossfadeRafRef.current = window.requestAnimationFrame(tick);
    },
    [flushPendingBlobRevokes, setImageLayersForBuffer, setLayerOpacity]
  );

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    ensurePmtilesProtocol();

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: styleFor(opacity, variable, model, region),
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
  }, [opacity, variable, model, region, view.center, view.zoom]);

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

      const urlsToRevoke = new Set<string>();
      for (const entry of loadedImageUrlsRef.current.values()) {
        if (entry.revokeUrl) {
          urlsToRevoke.add(entry.revokeUrl);
        }
      }
      for (const url of pendingBlobRevokesRef.current) {
        urlsToRevoke.add(url);
      }
      for (const url of Object.values(assignedSourceMapUrlsRef.current)) {
        if (isBlobUrl(url)) {
          urlsToRevoke.add(url);
        }
      }
      for (const url of urlsToRevoke) {
        URL.revokeObjectURL(url);
      }

      loadedImageUrlsRef.current.clear();
      failedImageUrlsRef.current.clear();
      inflightImageLoadsRef.current.clear();
      pendingBlobRevokesRef.current.clear();
      assignedSourceMapUrlsRef.current = { a: TRANSPARENT_IMAGE_URL, b: TRANSPARENT_IMAGE_URL };
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

    if (map.getLayer(IMG_LAYER_A)) {
      map.setPaintProperty(IMG_LAYER_A, "raster-resampling", resamplingMode);
      map.setLayerZoomRange(IMG_LAYER_A, overlayMinZoom, 24);
    }

    if (map.getLayer(IMG_LAYER_B)) {
      map.setPaintProperty(IMG_LAYER_B, "raster-resampling", resamplingMode);
      map.setLayerZoomRange(IMG_LAYER_B, overlayMinZoom, 24);
    }
  }, [isLoaded, imageCoordinates, overlayMinZoom, resamplingMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    const token = ++renderTokenRef.current;

    const hideOverlay = () => {
      if (token !== renderTokenRef.current) {
        return;
      }
      activeImageUrlRef.current = "";
      hideImageLayers(map);
      flushPendingBlobRevokes();
    };

    const targetImageUrl = frameImageUrl?.trim() ?? "";
    if (!targetImageUrl) {
      hideOverlay();
      onFrameSettled?.("");
      return;
    }

    if (activeImageUrlRef.current === targetImageUrl) {
      setImageLayersForBuffer(map, activeImageBufferRef.current, opacity);
      onFrameSettled?.(targetImageUrl);
      return;
    }

    void preloadImageUrl(targetImageUrl)
      .then(async (prepared) => {
        if (token !== renderTokenRef.current) {
          return;
        }
        if (!prepared) {
          hideOverlay();
          return;
        }

        const hasActiveImage = Boolean(activeImageUrlRef.current);
        const nextBuffer: ActiveImageBuffer = hasActiveImage
          ? activeImageBufferRef.current === "a"
            ? "b"
            : "a"
          : activeImageBufferRef.current;

        const sourceId = nextBuffer === "a" ? IMG_SOURCE_A : IMG_SOURCE_B;
        const imageSource = map.getSource(sourceId);
        if (!setImageSourceUrl(imageSource, prepared.mapUrl, imageCoordinates)) {
          failedImageUrlsRef.current.add(targetImageUrl);
          onFrameImageError?.(targetImageUrl);
          hideOverlay();
          return;
        }

        assignSourceMapUrl(nextBuffer, prepared.mapUrl);

        const sourceSettled = await waitForImageSourceSettled(map, sourceId, token);
        if (token !== renderTokenRef.current) {
          return;
        }
        if (!sourceSettled) {
          failedImageUrlsRef.current.add(targetImageUrl);
          onFrameImageError?.(targetImageUrl);
          hideOverlay();
          return;
        }

        if (hasActiveImage && crossfade) {
          runImageCrossfade(map, activeImageBufferRef.current, nextBuffer, opacity);
        } else {
          activeImageBufferRef.current = nextBuffer;
          setImageLayersForBuffer(map, nextBuffer, opacity);
        }

        activeImageUrlRef.current = targetImageUrl;
        flushPendingBlobRevokes();
        onFrameSettled?.(targetImageUrl);
      })
      .catch(() => {
        if (token !== renderTokenRef.current) {
          return;
        }
        hideOverlay();
      });
  }, [
    assignSourceMapUrl,
    crossfade,
    flushPendingBlobRevokes,
    frameImageUrl,
    hideImageLayers,
    imageCoordinates,
    isLoaded,
    onFrameImageError,
    onFrameSettled,
    opacity,
    preloadImageUrl,
    runImageCrossfade,
    setImageLayersForBuffer,
    waitForImageSourceSettled,
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

    if (!activeImageUrlRef.current) {
      hideImageLayers(map);
      return;
    }

    setImageLayersForBuffer(map, activeImageBufferRef.current, opacity);
  }, [hideImageLayers, isLoaded, opacity, setImageLayersForBuffer]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }
    map.easeTo({ center: view.center, zoom: view.zoom, duration: 600 });
  }, [view, isLoaded]);

  return <div ref={mapContainerRef} className="absolute inset-0" aria-label="Weather map" />;
}
