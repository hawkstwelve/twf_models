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

const IMAGE_CROSSFADE_DURATION_MS = 60;
const IMAGE_PREFETCH_THROTTLE_MS = 24;
const HIDDEN_OPACITY = 0;
const TRANSPARENT_IMAGE_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVQImWP8z/D/PwMDAwMjIAMAFAIB7l9d0QAAAABJRU5ErkJggg==";

const IMG_SOURCE_A = "twf-img-a";
const IMG_SOURCE_B = "twf-img-b";
const IMG_LAYER_A = "twf-img-a";
const IMG_LAYER_B = "twf-img-b";

type ActiveImageBuffer = "a" | "b";
type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];

type MutableImageSource = maplibregl.ImageSource & {
  updateImage?: (options: { url: string; coordinates: ImageCoordinates }) => maplibregl.ImageSource;
  setCoordinates?: (coordinates: ImageCoordinates) => void;
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
  if (!imageSource || typeof imageSource.updateImage !== "function") {
    return false;
  }
  imageSource.updateImage({ url, coordinates });
  return true;
}

function setLayerVisibility(map: maplibregl.Map, id: string, visible: boolean): void {
  if (!map.getLayer(id)) {
    return;
  }
  map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
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
          "raster-opacity": opacity,
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
  const [isLoaded, setIsLoaded] = useState(false);

  const onRequestUrlRef = useRef(onRequestUrl);
  const activeImageBufferRef = useRef<ActiveImageBuffer>("a");
  const activeImageUrlRef = useRef<string>("");
  const crossfadeRafRef = useRef<number | null>(null);
  const renderTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);

  const loadedImageUrlsRef = useRef<Set<string>>(new Set());
  const failedImageUrlsRef = useRef<Set<string>>(new Set());
  const inflightImageLoadsRef = useRef<Map<string, Promise<boolean>>>(new Map());

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

  const preloadImageUrl = useCallback(
    async (url: string): Promise<boolean> => {
      const normalizedUrl = url.trim();
      if (!normalizedUrl) {
        return false;
      }
      if (loadedImageUrlsRef.current.has(normalizedUrl)) {
        onFrameImageReady?.(normalizedUrl);
        return true;
      }

      const inflight = inflightImageLoadsRef.current.get(normalizedUrl);
      if (inflight) {
        return inflight;
      }

      const promise = new Promise<boolean>((resolve) => {
        const image = new Image();
        image.crossOrigin = "anonymous";
        image.decoding = "async";

        const cleanup = () => {
          image.onload = null;
          image.onerror = null;
          inflightImageLoadsRef.current.delete(normalizedUrl);
        };

        image.onload = () => {
          cleanup();
          failedImageUrlsRef.current.delete(normalizedUrl);
          loadedImageUrlsRef.current.add(normalizedUrl);
          onFrameImageReady?.(normalizedUrl);
          resolve(true);
        };

        image.onerror = () => {
          cleanup();
          failedImageUrlsRef.current.add(normalizedUrl);
          onFrameImageError?.(normalizedUrl);
          resolve(false);
        };

        image.src = normalizedUrl;
      });

      inflightImageLoadsRef.current.set(normalizedUrl, promise);
      return promise;
    },
    [onFrameImageError, onFrameImageReady]
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
        map.triggerRepaint();
        return;
      }

      const fromLayer = fromBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
      const toLayer = toBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
      const startedAt = performance.now();
      setLayerVisibility(map, fromLayer, true);
      setLayerVisibility(map, toLayer, true);

      const tick = (now: number) => {
        const progress = Math.min(1, (now - startedAt) / IMAGE_CROSSFADE_DURATION_MS);
        const fromOpacity = targetOpacity * (1 - progress);
        const toOpacity = targetOpacity * progress;

        setLayerOpacity(map, fromLayer, fromOpacity);
        setLayerOpacity(map, toLayer, toOpacity);
        map.triggerRepaint();

        if (progress >= 1) {
          activeImageBufferRef.current = toBuffer;
          setLayerVisibility(map, fromLayer, false);
          setLayerVisibility(map, toLayer, true);
          setLayerOpacity(map, fromLayer, HIDDEN_OPACITY);
          setLayerOpacity(map, toLayer, targetOpacity);
          crossfadeRafRef.current = null;
          map.triggerRepaint();
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
  }, []);

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

    if (map.getLayer(IMG_LAYER_A)) {
      map.setPaintProperty(IMG_LAYER_A, "raster-resampling", resamplingMode);
      map.setPaintProperty(IMG_LAYER_A, "raster-fade-duration", 0);
      map.setLayerZoomRange(IMG_LAYER_A, overlayMinZoom, 24);
    }

    if (map.getLayer(IMG_LAYER_B)) {
      map.setPaintProperty(IMG_LAYER_B, "raster-resampling", resamplingMode);
      map.setPaintProperty(IMG_LAYER_B, "raster-fade-duration", 0);
      map.setLayerZoomRange(IMG_LAYER_B, overlayMinZoom, 24);
    }
  }, [imageCoordinates, isLoaded, overlayMinZoom, resamplingMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    if (!activeImageUrlRef.current) {
      hideImageLayers(map);
      map.triggerRepaint();
      return;
    }

    setImageLayersForBuffer(map, activeImageBufferRef.current, opacity);
    map.triggerRepaint();
  }, [hideImageLayers, isLoaded, opacity, setImageLayersForBuffer]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    const token = ++renderTokenRef.current;
    const targetImageUrl = frameImageUrl?.trim() ?? "";

    if (!targetImageUrl) {
      activeImageUrlRef.current = "";
      hideImageLayers(map);
      map.triggerRepaint();
      return;
    }

    if (activeImageUrlRef.current === targetImageUrl) {
      setImageLayersForBuffer(map, activeImageBufferRef.current, opacity);
      map.triggerRepaint();
      return;
    }

    void preloadImageUrl(targetImageUrl)
      .then((ready) => {
        if (!ready || token !== renderTokenRef.current) {
          if (token === renderTokenRef.current) {
            activeImageUrlRef.current = "";
            hideImageLayers(map);
            map.triggerRepaint();
          }
          return;
        }

        const hadActiveImage = Boolean(activeImageUrlRef.current);
        const nextBuffer: ActiveImageBuffer = hadActiveImage
          ? activeImageBufferRef.current === "a"
            ? "b"
            : "a"
          : activeImageBufferRef.current;

        const sourceId = nextBuffer === "a" ? IMG_SOURCE_A : IMG_SOURCE_B;
        const source = map.getSource(sourceId);
        if (!setImageSourceUrl(source, targetImageUrl, imageCoordinates)) {
          onFrameImageError?.(targetImageUrl);
          activeImageUrlRef.current = "";
          hideImageLayers(map);
          map.triggerRepaint();
          return;
        }

        map.triggerRepaint();

        if (hadActiveImage && crossfade) {
          runImageCrossfade(map, activeImageBufferRef.current, nextBuffer, opacity);
        } else {
          activeImageBufferRef.current = nextBuffer;
          setImageLayersForBuffer(map, nextBuffer, opacity);
          map.triggerRepaint();
        }

        activeImageUrlRef.current = targetImageUrl;
      })
      .catch(() => {
        if (token !== renderTokenRef.current) {
          return;
        }
        activeImageUrlRef.current = "";
        hideImageLayers(map);
        map.triggerRepaint();
      });
  }, [
    crossfade,
    frameImageUrl,
    hideImageLayers,
    imageCoordinates,
    isLoaded,
    onFrameImageError,
    opacity,
    preloadImageUrl,
    runImageCrossfade,
    setImageLayersForBuffer,
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
        await preloadImageUrl(url);
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
  }, [prefetchFrameImageUrls, preloadImageUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }
    map.easeTo({ center: view.center, zoom: view.zoom, duration: 600 });
  }, [isLoaded, view]);

  return <div ref={mapContainerRef} className="absolute inset-0" aria-label="Weather map" />;
}
