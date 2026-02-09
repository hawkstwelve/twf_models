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
};

const SCRUB_SWAP_TIMEOUT_MS = 650;
const AUTOPLAY_SWAP_TIMEOUT_MS = 1500;
const CONTINUOUS_CROSSFADE_MS = 120;

type OverlayBuffer = "a" | "b";
type PlaybackMode = "autoplay" | "scrub";

function sourceId(buffer: OverlayBuffer): string {
  return `twf-overlay-${buffer}`;
}

function layerId(buffer: OverlayBuffer): string {
  return `twf-overlay-${buffer}`;
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

function styleFor(overlayUrl: string, opacity: number): StyleSpecification {
  return {
    version: 8,
    sources: {
      "twf-basemap": {
        type: "raster",
        tiles: CARTO_LIGHT_BASE_TILES,
        tileSize: 256,
        attribution: BASEMAP_ATTRIBUTION,
      },
      [sourceId("a")]: {
        type: "raster",
        tiles: [overlayUrl],
        tileSize: 256,
      },
      [sourceId("b")]: {
        type: "raster",
        tiles: [overlayUrl],
        tileSize: 256,
      },
      [prefetchSourceId(1)]: {
        type: "raster",
        tiles: [overlayUrl],
        tileSize: 256,
      },
      [prefetchSourceId(2)]: {
        type: "raster",
        tiles: [overlayUrl],
        tileSize: 256,
      },
      "twf-labels": {
        type: "raster",
        tiles: CARTO_LIGHT_LABEL_TILES,
        tileSize: 256,
      },
    },
    layers: [
      {
        id: "twf-basemap",
        type: "raster",
        source: "twf-basemap",
      },
      {
        id: layerId("a"),
        type: "raster",
        source: sourceId("a"),
        paint: {
          "raster-opacity": opacity,
          "raster-resampling": "nearest",
        },
      },
      {
        id: layerId("b"),
        type: "raster",
        source: sourceId("b"),
        paint: {
          "raster-opacity": 0,
          "raster-resampling": "nearest",
        },
      },
      {
        id: prefetchLayerId(1),
        type: "raster",
        source: prefetchSourceId(1),
        paint: {
          "raster-opacity": 0,
          "raster-resampling": "nearest",
        },
      },
      {
        id: prefetchLayerId(2),
        type: "raster",
        source: prefetchSourceId(2),
        paint: {
          "raster-opacity": 0,
          "raster-resampling": "nearest",
        },
      },
      {
        id: "twf-labels",
        type: "raster",
        source: "twf-labels",
      },
    ],
  };
}

type MapCanvasProps = {
  tileUrl: string;
  region: string;
  opacity: number;
  mode: PlaybackMode;
  prefetchTileUrls?: string[];
  crossfade?: boolean;
  onFrameSettled?: (tileUrl: string) => void;
  onTileReady?: (tileUrl: string) => void;
};

export function MapCanvas({
  tileUrl,
  region,
  opacity,
  mode,
  prefetchTileUrls = [],
  crossfade = false,
  onFrameSettled,
  onTileReady,
}: MapCanvasProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const activeBufferRef = useRef<OverlayBuffer>("a");
  const activeTileUrlRef = useRef(tileUrl);
  const swapTokenRef = useRef(0);
  const prefetchTokenRef = useRef(0);
  const prefetchUrlsRef = useRef<[string, string]>(["", ""]);
  const fadeTokenRef = useRef(0);
  const fadeRafRef = useRef<number | null>(null);

  const view = useMemo(() => {
    return REGION_VIEWS[region] ?? {
      center: [DEFAULTS.center[1], DEFAULTS.center[0]] as [number, number],
      zoom: DEFAULTS.zoom,
    };
  }, [region]);

  const setLayerOpacity = useCallback((map: maplibregl.Map, id: string, value: number) => {
    if (!map.getLayer(id)) {
      return;
    }
    map.setPaintProperty(id, "raster-opacity", value);
  }, []);

  const cancelCrossfade = useCallback(() => {
    fadeTokenRef.current += 1;
    if (fadeRafRef.current !== null) {
      window.cancelAnimationFrame(fadeRafRef.current);
      fadeRafRef.current = null;
    }
  }, []);

  const runCrossfade = useCallback(
    (map: maplibregl.Map, fromBuffer: OverlayBuffer, toBuffer: OverlayBuffer, targetOpacity: number) => {
      cancelCrossfade();
      const token = fadeTokenRef.current;
      const started = performance.now();

      const tick = (now: number) => {
        if (token !== fadeTokenRef.current) {
          return;
        }
        const progress = Math.min(1, (now - started) / CONTINUOUS_CROSSFADE_MS);
        const fromOpacity = targetOpacity * (1 - progress);
        const toOpacity = targetOpacity * progress;

        setLayerOpacity(map, layerId(fromBuffer), fromOpacity);
        setLayerOpacity(map, layerId(toBuffer), toOpacity);

        if (progress < 1) {
          fadeRafRef.current = window.requestAnimationFrame(tick);
          return;
        }

        fadeRafRef.current = null;
      };

      setLayerOpacity(map, layerId(fromBuffer), targetOpacity);
      setLayerOpacity(map, layerId(toBuffer), 0);
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

      const readyForMode = () => {
        if (modeValue === "autoplay") {
          // For autoplay, prefer waiting until the map reports an idle cycle after source updates.
          return map.isSourceLoaded(source);
        }
        return map.isSourceLoaded(source);
      };

      const onSourceData = (event: maplibregl.MapSourceDataEvent) => {
        if (event.sourceId !== source) {
          return;
        }
        if (modeValue === "scrub" && readyForMode()) {
          finishReady();
        }
      };

      const onIdle = () => {
        if (modeValue !== "autoplay") {
          return;
        }
        if (readyForMode()) {
          finishReady();
        }
      };

      map.on("sourcedata", onSourceData);
      map.on("idle", onIdle);

      timeoutId = window.setTimeout(() => finishTimeout(), timeoutMs);

      if (modeValue === "scrub" && readyForMode()) {
        finishReady();
      }

      return () => {
        done = true;
        cleanup();
      };
    },
    []
  );

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: styleFor(tileUrl, opacity),
      center: view.center,
      zoom: view.zoom,
      minZoom: 3,
      maxZoom: 11,
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

    map.on("load", () => {
      setIsLoaded(true);
    });

    mapRef.current = map;

    return () => {
      cancelCrossfade();
      map.remove();
      mapRef.current = null;
      setIsLoaded(false);
    };
  }, [cancelCrossfade]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    if (tileUrl === activeTileUrlRef.current) {
      return waitForSourceReady(
        map,
        sourceId(activeBufferRef.current),
        mode,
        () => {
          onTileReady?.(tileUrl);
          onFrameSettled?.(tileUrl);
        },
        () => {
          if (mode === "scrub") {
            onTileReady?.(tileUrl);
            onFrameSettled?.(tileUrl);
          }
        }
      );
    }

    const inactiveBuffer = otherBuffer(activeBufferRef.current);
    const inactiveSource = map.getSource(sourceId(inactiveBuffer)) as
      | maplibregl.RasterTileSource
      | undefined;
    if (!inactiveSource || typeof inactiveSource.setTiles !== "function") {
      return;
    }

    inactiveSource.setTiles([tileUrl]);
    const token = ++swapTokenRef.current;

    const finishSwap = () => {
      if (token !== swapTokenRef.current) {
        return;
      }

      const previousActive = activeBufferRef.current;
      activeBufferRef.current = inactiveBuffer;
      activeTileUrlRef.current = tileUrl;

      if (crossfade) {
        runCrossfade(map, previousActive, inactiveBuffer, opacity);
      } else {
        cancelCrossfade();
        // Make swap atomic: set new layer visible first, then hide old on next frame
        setLayerOpacity(map, layerId(inactiveBuffer), opacity);
        window.requestAnimationFrame(() => {
          setLayerOpacity(map, layerId(previousActive), 0);
        });
      }

      onTileReady?.(tileUrl);
      onFrameSettled?.(tileUrl);
    };

    return waitForSourceReady(
      map,
      sourceId(inactiveBuffer),
      mode,
      finishSwap,
      () => {
        // On timeout in scrub mode, do NOT swap to incomplete buffer.
        // Keep the old buffer visible until the new one is ready.
        if (mode === "scrub") {
          // Optionally notify that frame settled even if swap didn't occur
          onTileReady?.(tileUrl);
          onFrameSettled?.(tileUrl);
        }
      }
    );
  }, [
    tileUrl,
    isLoaded,
    mode,
    opacity,
    crossfade,
    waitForSourceReady,
    runCrossfade,
    cancelCrossfade,
    setLayerOpacity,
    onFrameSettled,
    onTileReady,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    const token = ++prefetchTokenRef.current;
    const urls: [string, string] = [prefetchTileUrls[0] ?? "", prefetchTileUrls[1] ?? ""];
    const cleanups: Array<() => void> = [];

    urls.forEach((url, idx) => {
      const source = map.getSource(prefetchSourceId(idx + 1)) as maplibregl.RasterTileSource | undefined;
      if (!source || typeof source.setTiles !== "function") {
        return;
      }

      if (!url) {
        prefetchUrlsRef.current[idx] = "";
        return;
      }

      if (prefetchUrlsRef.current[idx] === url) {
        return;
      }

      prefetchUrlsRef.current[idx] = url;
      source.setTiles([url]);

      const cleanup = waitForSourceReady(
        map,
        prefetchSourceId(idx + 1),
        "scrub",
        () => {
          if (token !== prefetchTokenRef.current) {
            return;
          }
          if (prefetchUrlsRef.current[idx] !== url) {
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
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    const activeBuffer = activeBufferRef.current;
    const inactiveBuffer = otherBuffer(activeBuffer);

    if (!crossfade) {
      cancelCrossfade();
    }

    setLayerOpacity(map, layerId(activeBuffer), opacity);
    setLayerOpacity(map, layerId(inactiveBuffer), 0);
    setLayerOpacity(map, prefetchLayerId(1), 0);
    setLayerOpacity(map, prefetchLayerId(2), 0);
  }, [opacity, isLoaded, crossfade, cancelCrossfade, setLayerOpacity]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }
    map.easeTo({ center: view.center, zoom: view.zoom, duration: 600 });
  }, [view, isLoaded]);

  return <div ref={mapContainerRef} className="absolute inset-0" aria-label="Weather map" />;
}
