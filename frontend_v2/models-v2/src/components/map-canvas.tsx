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
const OVERLAY_CANVAS_WIDTH = 2048;
const OVERLAY_CANVAS_HEIGHT = 2046;

const IMG_SOURCE_A = "twf-canvas-a";
const IMG_SOURCE_B = "twf-canvas-b";
const IMG_LAYER_A = "twf-img-a";
const IMG_LAYER_B = "twf-img-b";

type ActiveImageBuffer = "a" | "b";
type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];

type MutableCanvasSource = maplibregl.CanvasSource & {
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

function canvasSourceFor(canvas: HTMLCanvasElement, coordinates: ImageCoordinates) {
  return {
    type: "canvas" as const,
    canvas,
    coordinates,
    animate: true,
  };
}

async function fetchBitmap(url: string): Promise<ImageBitmap> {
  const response = await fetch(url, { mode: "cors", credentials: "omit" });
  if (!response.ok) {
    throw new Error(`Failed to fetch overlay bitmap (${response.status} ${response.statusText}) for ${url}`);
  }
  const blob = await response.blob();
  return createImageBitmap(blob);
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

function styleFor(
  canvasA: HTMLCanvasElement,
  canvasB: HTMLCanvasElement,
  imageCoordinates: ImageCoordinates,
  resampling: "nearest" | "linear",
  minZoom: number
): StyleSpecification {
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
      [IMG_SOURCE_A]: canvasSourceFor(canvasA, imageCoordinates) as any,
      [IMG_SOURCE_B]: canvasSourceFor(canvasB, imageCoordinates) as any,
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
        minzoom: minZoom,
        layout: { visibility: "none" as const },
        paint: {
          "raster-opacity": HIDDEN_OPACITY,
          "raster-resampling": resampling,
          "raster-fade-duration": 0,
        },
      },
      {
        id: IMG_LAYER_B,
        type: "raster" as const,
        source: IMG_SOURCE_B,
        minzoom: minZoom,
        layout: { visibility: "none" as const },
        paint: {
          "raster-opacity": HIDDEN_OPACITY,
          "raster-resampling": resampling,
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
  const mapDestroyedRef = useRef(false);
  const overlayReadyRef = useRef(false);
  const [isLoaded, setIsLoaded] = useState(false);

  const onRequestUrlRef = useRef(onRequestUrl);
  const activeImageBufferRef = useRef<ActiveImageBuffer>("a");
  const activeImageUrlRef = useRef<string>("");
  const crossfadeRafRef = useRef<number | null>(null);
  const renderTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);

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

  const setLayerOpacity = useCallback((map: maplibregl.Map, id: string, value: number) => {
    if (!isMapStyleReady(map)) {
      return;
    }
    if (!map.getLayer(id)) {
      return;
    }
    try {
      map.setPaintProperty(id, "raster-opacity", value);
    } catch {
      // Style/source may have been torn down mid-frame.
    }
  }, []);

  const setImageLayersForBuffer = useCallback(
    (map: maplibregl.Map, activeBuffer: ActiveImageBuffer, targetOpacity: number) => {
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
      setLayerOpacity(map, IMG_LAYER_A, HIDDEN_OPACITY);
      setLayerOpacity(map, IMG_LAYER_B, HIDDEN_OPACITY);
    },
    [setLayerOpacity]
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
                  "raster-opacity": targetOpacity,
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
                layout: { visibility: "none" },
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
      setLayerOpacity(map, IMG_LAYER_A, targetOpacity);
      setLayerOpacity(map, IMG_LAYER_B, HIDDEN_OPACITY);
      setLayerVisibility(map, IMG_LAYER_A, true);
      setLayerVisibility(map, IMG_LAYER_B, false);

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
      (window as any).__twfOverlaySourceAUrl = activeImageUrlRef.current;
      console.info("[MapCanvas] overlay initialized", {
        source: IMG_SOURCE_A,
        url: activeImageUrlRef.current,
      });
      return true;
    },
    [canMutateMap, setLayerOpacity]
  );

  const waitForNextRenderOrIdle = useCallback((map: maplibregl.Map, token: number): Promise<boolean> => {
    return new Promise((resolve) => {
      if (!canMutateMap(map)) {
        resolve(false);
        return;
      }

      let done = false;
      let timeoutId: number | null = null;

      const cleanup = () => {
        map.off("render", onRender);
        map.off("idle", onIdle);
        if (timeoutId !== null) {
          window.clearTimeout(timeoutId);
          timeoutId = null;
        }
      };

      const finish = () => {
        if (done) return;
        done = true;
        cleanup();
        resolve(token === renderTokenRef.current && canMutateMap(map));
      };

      const onRender = () => finish();
      const onIdle = () => finish();

      map.once("render", onRender);
      map.once("idle", onIdle);
      timeoutId = window.setTimeout(finish, 120);
      try {
        map.triggerRepaint();
      } catch {
        finish();
      }
    });
  }, [canMutateMap]);

  const runImageCrossfade = useCallback(
    (
      map: maplibregl.Map,
      fromBuffer: ActiveImageBuffer,
      toBuffer: ActiveImageBuffer,
      targetOpacity: number,
      token: number
    ) => {
      if (crossfadeRafRef.current !== null) {
        window.cancelAnimationFrame(crossfadeRafRef.current);
        crossfadeRafRef.current = null;
      }

      if (
        !overlayReadyRef.current ||
        !canMutateMap(map) ||
        !hasSource(map, IMG_SOURCE_A) ||
        !hasSource(map, IMG_SOURCE_B) ||
        !hasLayer(map, IMG_LAYER_A) ||
        !hasLayer(map, IMG_LAYER_B) ||
        token !== renderTokenRef.current
      ) {
        return;
      }

      if (fromBuffer === toBuffer) {
        activeImageBufferRef.current = toBuffer;
        setImageLayersForBuffer(map, toBuffer, targetOpacity);
        if (canMutateMap(map)) {
          map.triggerRepaint();
        }
        return;
      }

      const fromLayer = fromBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
      const toLayer = toBuffer === "a" ? IMG_LAYER_A : IMG_LAYER_B;
      const startedAt = performance.now();
      setLayerVisibility(map, fromLayer, true);
      setLayerVisibility(map, toLayer, true);

      const tick = (now: number) => {
        if (
          !overlayReadyRef.current ||
          token !== renderTokenRef.current ||
          !canMutateMap(map) ||
          !hasSource(map, IMG_SOURCE_A) ||
          !hasSource(map, IMG_SOURCE_B) ||
          !hasLayer(map, IMG_LAYER_A) ||
          !hasLayer(map, IMG_LAYER_B)
        ) {
          if (crossfadeRafRef.current !== null) {
            window.cancelAnimationFrame(crossfadeRafRef.current);
            crossfadeRafRef.current = null;
          }
          return;
        }

        const progress = Math.min(1, (now - startedAt) / IMAGE_CROSSFADE_DURATION_MS);
        const fromOpacity = targetOpacity * (1 - progress);
        const toOpacity = targetOpacity * progress;

        setLayerOpacity(map, fromLayer, fromOpacity);
        setLayerOpacity(map, toLayer, toOpacity);
        if (canMutateMap(map)) {
          map.triggerRepaint();
        }

        if (progress >= 1) {
          activeImageBufferRef.current = toBuffer;
          setLayerVisibility(map, fromLayer, false);
          setLayerVisibility(map, toLayer, true);
          setLayerOpacity(map, fromLayer, HIDDEN_OPACITY);
          setLayerOpacity(map, toLayer, targetOpacity);
          crossfadeRafRef.current = null;
          if (canMutateMap(map)) {
            map.triggerRepaint();
          }
          return;
        }

        crossfadeRafRef.current = window.requestAnimationFrame(tick);
      };

      crossfadeRafRef.current = window.requestAnimationFrame(tick);
    },
    [canMutateMap, setImageLayersForBuffer, setLayerOpacity]
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
      style: styleFor(canvasA, canvasB, imageCoordinates, resamplingMode, overlayMinZoom),
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
    (window as any).__twfOverlayReady = false;
    (window as any).__twfOverlaySourceAUrl = "";

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    map.on("load", () => {
      setIsLoaded(true);
    });

    mapRef.current = map;
    (window as any).__twfMap = map;
  }, [imageCoordinates, overlayMinZoom, resamplingMode, view.center, view.zoom]);

  useEffect(() => {
    return () => {
      if (crossfadeRafRef.current !== null) {
        window.cancelAnimationFrame(crossfadeRafRef.current);
        crossfadeRafRef.current = null;
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
      (window as any).__twfOverlayReady = false;
      (window as any).__twfOverlaySourceAUrl = "";
      setIsLoaded(false);
      canvasARef.current = null;
      canvasBRef.current = null;
      ctxARef.current = null;
      ctxBRef.current = null;
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
  }, [imageCoordinates, isLoaded, overlayMinZoom, resamplingMode]);

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

    setImageLayersForBuffer(map, activeImageBufferRef.current, opacity);
    if (isMapStyleReady(map)) {
      map.triggerRepaint();
    }
  }, [hideImageLayers, isLoaded, opacity, setImageLayersForBuffer]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded || !isMapStyleReady(map)) {
      return;
    }

    const token = ++renderTokenRef.current;
    if (crossfadeRafRef.current !== null) {
      window.cancelAnimationFrame(crossfadeRafRef.current);
      crossfadeRafRef.current = null;
    }
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
      setImageLayersForBuffer(map, activeImageBufferRef.current, opacity);
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

        const hadActiveImage = Boolean(activeImageUrlRef.current);
        const nextBuffer: ActiveImageBuffer = hadActiveImage
          ? activeImageBufferRef.current === "a"
            ? "b"
            : "a"
          : activeImageBufferRef.current;

        const targetCtx = nextBuffer === "a" ? ctxARef.current : ctxBRef.current;
        if (!targetCtx) {
          onFrameImageError?.(targetImageUrl);
          activeImageUrlRef.current = "";
          hideImageLayers(map);
          map.triggerRepaint();
          return;
        }

        let bitmap: ImageBitmap | null = null;
        try {
          bitmap = await fetchBitmap(targetImageUrl);
        } catch {
          onFrameImageError?.(targetImageUrl);
          activeImageUrlRef.current = "";
          hideImageLayers(map);
          map.triggerRepaint();
          return;
        }

        if (token !== renderTokenRef.current || !canMutateMap(map)) {
          bitmap.close();
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
          bitmap.close();
          if (token === renderTokenRef.current && canMutateMap(map)) {
            activeImageUrlRef.current = "";
            hideImageLayers(map);
            map.triggerRepaint();
          }
          return;
        }

        try {
          const targetCanvas = targetCtx.canvas;
          targetCtx.clearRect(0, 0, targetCanvas.width, targetCanvas.height);
          targetCtx.drawImage(bitmap, 0, 0, targetCanvas.width, targetCanvas.height);
        } catch {
          bitmap.close();
          onFrameImageError?.(targetImageUrl);
          activeImageUrlRef.current = "";
          hideImageLayers(map);
          map.triggerRepaint();
          return;
        }
        bitmap.close();

        if (!canMutateMap(map)) {
          return;
        }

        const glVersion = (() => {
          const gl = (map as any)?.painter?.context?.gl;
          if (!gl || typeof gl.getParameter !== "function") {
            return undefined;
          }
          try {
            return gl.getParameter(gl.VERSION);
          } catch {
            return undefined;
          }
        })();
        console.log("[OverlayCanvasApply]", {
          url: targetImageUrl,
          buffer: nextBuffer,
          zoom: map.getZoom(),
          gl: glVersion,
        });
        onFrameImageReady?.(targetImageUrl);

        map.triggerRepaint();
        const renderSettled = await waitForNextRenderOrIdle(map, token);
        if (!renderSettled || token !== renderTokenRef.current || !canMutateMap(map)) {
          return;
        }

        if (
          hadActiveImage &&
          crossfade &&
          overlayReadyRef.current &&
          hasLayer(map, IMG_LAYER_A) &&
          hasLayer(map, IMG_LAYER_B)
        ) {
          runImageCrossfade(map, activeImageBufferRef.current, nextBuffer, opacity, token);
        } else {
          activeImageBufferRef.current = nextBuffer;
          setImageLayersForBuffer(map, nextBuffer, opacity);
          map.triggerRepaint();
        }

        activeImageUrlRef.current = targetImageUrl;
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
    waitForNextRenderOrIdle,
    runImageCrossfade,
    setImageLayersForBuffer,
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
          const bitmap = await fetchBitmap(url);
          bitmap.close();
          onFrameImageReady?.(url);
        } catch {
          onFrameImageError?.(url);
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
  }, [onFrameImageError, onFrameImageReady, prefetchFrameImageUrls]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }
    map.easeTo({ center: view.center, zoom: view.zoom, duration: 600 });
  }, [isLoaded, view]);

  return <div ref={mapContainerRef} className="absolute inset-0" aria-label="Weather map" />;
}
