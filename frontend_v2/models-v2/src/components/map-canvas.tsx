import { useEffect, useMemo, useRef, useState } from "react";
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

type OverlayBuffer = "a" | "b";

function sourceId(buffer: OverlayBuffer): string {
  return `twf-overlay-${buffer}`;
}

function layerId(buffer: OverlayBuffer): string {
  return `twf-overlay-${buffer}`;
}

function otherBuffer(buffer: OverlayBuffer): OverlayBuffer {
  return buffer === "a" ? "b" : "a";
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
  onFrameSettled?: (tileUrl: string) => void;
};

export function MapCanvas({ tileUrl, region, opacity, onFrameSettled }: MapCanvasProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const activeBufferRef = useRef<OverlayBuffer>("a");
  const activeTileUrlRef = useRef(tileUrl);
  const swapTokenRef = useRef(0);

  const view = useMemo(() => {
    return REGION_VIEWS[region] ?? {
      center: [DEFAULTS.center[1], DEFAULTS.center[0]] as [number, number],
      zoom: DEFAULTS.zoom,
    };
  }, [region]);

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
      map.remove();
      mapRef.current = null;
      setIsLoaded(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    const waitForSourceLoad = (buffer: OverlayBuffer, onDone: () => void) => {
      const loadTimeoutMs = 650;
      let done = false;
      let timeoutId: number | null = null;

      const finish = () => {
        if (done) return;
        done = true;
        if (timeoutId !== null) {
          window.clearTimeout(timeoutId);
          timeoutId = null;
        }
        map.off("sourcedata", onSourceData);
        onDone();
      };

      const isLoaded = () => map.isSourceLoaded(sourceId(buffer));
      const onSourceData = (event: maplibregl.MapSourceDataEvent) => {
        if (event.sourceId !== sourceId(buffer)) {
          return;
        }
        if (isLoaded()) {
          finish();
        }
      };

      map.on("sourcedata", onSourceData);
      timeoutId = window.setTimeout(() => finish(), loadTimeoutMs);
      if (isLoaded()) {
        finish();
      }

      return () => {
        done = true;
        if (timeoutId !== null) {
          window.clearTimeout(timeoutId);
        }
        map.off("sourcedata", onSourceData);
      };
    };

    if (tileUrl === activeTileUrlRef.current) {
      return waitForSourceLoad(activeBufferRef.current, () => onFrameSettled?.(tileUrl));
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
    const setLayerOpacity = (buffer: OverlayBuffer, value: number) => {
      if (!map.getLayer(layerId(buffer))) {
        return;
      }
      map.setPaintProperty(layerId(buffer), "raster-opacity", value);
    };

    const finishSwap = () => {
      if (token !== swapTokenRef.current) {
        return;
      }

      const previousActive = activeBufferRef.current;
      activeBufferRef.current = inactiveBuffer;
      activeTileUrlRef.current = tileUrl;
      setLayerOpacity(previousActive, 0);
      setLayerOpacity(inactiveBuffer, opacity);
      onFrameSettled?.(tileUrl);
    };

    return waitForSourceLoad(inactiveBuffer, finishSwap);
  }, [tileUrl, isLoaded, opacity, onFrameSettled]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }

    const activeBuffer = activeBufferRef.current;
    const inactiveBuffer = otherBuffer(activeBuffer);
    if (map.getLayer(layerId(activeBuffer))) {
      map.setPaintProperty(layerId(activeBuffer), "raster-opacity", opacity);
    }
    if (map.getLayer(layerId(inactiveBuffer))) {
      map.setPaintProperty(layerId(inactiveBuffer), "raster-opacity", 0);
    }
  }, [opacity, isLoaded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isLoaded) {
      return;
    }
    map.easeTo({ center: view.center, zoom: view.zoom, duration: 600 });
  }, [view, isLoaded]);

  return <div ref={mapContainerRef} className="absolute inset-0" aria-label="Weather map" />;
}
