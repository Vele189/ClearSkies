import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  addProtocol,
  removeProtocol,
} from "maplibre-gl";
import type { MapLayerMouseEvent } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  FULL_OPACITY,
  TRUSTED,
  UNCERTAIN,
  UNSCORED,
  UNSCORED_COLOR,
  UNTRUSTED,
  fillColor,
  hatchImage,
} from "../lib/ramp.ts";
import Legend from "./Legend.tsx";
import SearchBox from "./SearchBox.tsx";

const DEFAULT_BASEMAP = "https://tiles.openfreemap.org/styles/positron";

// Louisiana, roughly. The archive's own bounds take over once a real one is
// configured; this is what the map opens on before any tile has loaded.
const CENTER: [number, number] = [-91.5, 30.6];
const ZOOM = 6.6;

const SOURCE_ID = "clearskies-hexes";
const HATCH_ID = "clearskies-hatch";

// Four fill layers rather than one, because section 12 gives the four
// confidence bands four different treatments and an expression cannot switch a
// fill-pattern on and off. Ordered bottom to top: the unscored ground, then the
// scores, then the hatch over the ones not to be read too confidently.
const LAYERS = {
  unscored: "clearskies-hex-unscored",
  untrusted: "clearskies-hex-untrusted",
  fill: "clearskies-hex-fill",
  hatch: "clearskies-hex-hatch",
} as const;

const CLICKABLE = [LAYERS.fill, LAYERS.untrusted, LAYERS.unscored];

interface Props {
  onSelect: (h3: string) => void;
}

export default function MapView({ onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [showUntrusted, setShowUntrusted] = useState(false);
  const [tilesFailed, setTilesFailed] = useState(false);

  const tilesUrl = import.meta.env.VITE_TILES_URL;

  // Held in a ref so the map effect below can stay keyed to [] and not tear
  // down and rebuild the map every time the parent re-renders a new callback.
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const goTo = useCallback((lon: number, lat: number, zoom?: number) => {
    mapRef.current?.flyTo({ center: [lon, lat], zoom: zoom ?? 12, duration: 900 });
  }, []);

  useEffect(() => {
    if (!container.current) return;

    const protocol = new Protocol();
    addProtocol("pmtiles", protocol.tile);

    const map = new MapLibreMap({
      container: container.current,
      style: import.meta.env.VITE_BASEMAP_STYLE ?? DEFAULT_BASEMAP,
      center: CENTER,
      zoom: ZOOM,
      attributionControl: { compact: true },
    });
    mapRef.current = map;

    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-left");
    // Touch devices get pinch-zoom and drag-pan by default; the double-tap
    // handler is the one that fights with a two-finger zoom on a phone.
    map.touchZoomRotate.disableRotation();

    // An archive that 404s, a bucket without CORS, or a host that ignores Range
    // all surface here. Without this the map sits on the basemap looking
    // finished, which is the worst of the three possible outcomes.
    map.on("error", (event) => {
      // The event carries sourceId only when a source is what failed, and the
      // published type does not say so; narrow rather than cast.
      const detail: unknown = event;
      if (
        detail &&
        typeof detail === "object" &&
        "sourceId" in detail &&
        detail.sourceId === SOURCE_ID
      ) {
        setTilesFailed(true);
      }
    });

    map.on("load", () => {
      if (!tilesUrl) return; // No archive configured; the banner explains it.

      const hatch = hatchImage();
      if (!map.hasImage(HATCH_ID)) {
        map.addImage(HATCH_ID, hatch);
      }

      map.addSource(SOURCE_ID, { type: "vector", url: `pmtiles://${tilesUrl}` });

      // Hexes with no score at all. Off the colour ramp on purpose: running a
      // missing percentile through the ramp as zero would paint a cell nobody
      // measured as the cleanest in the state, which is the zero-for-missing
      // failure methodology section 11 rules out, arriving by the back door.
      map.addLayer({
        id: LAYERS.unscored,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": "hexes",
        filter: UNSCORED,
        paint: { "fill-color": UNSCORED_COLOR, "fill-opacity": 0.4 },
      });

      // Section 12: below 0.40 a hex is hidden behind a toggle rather than
      // shown. It is still in the archive, and the legend says how to see it.
      map.addLayer({
        id: LAYERS.untrusted,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": "hexes",
        filter: UNTRUSTED,
        layout: { visibility: "none" },
        paint: { "fill-color": fillColor, "fill-opacity": 0.45 },
      });

      map.addLayer({
        id: LAYERS.fill,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": "hexes",
        filter: ["any", TRUSTED, UNCERTAIN],
        paint: {
          "fill-color": fillColor,
          "fill-opacity": FULL_OPACITY,
          "fill-outline-color": "rgba(0,0,0,0.08)",
        },
      });

      // Drawn over the low-confidence hexes only, so they keep their colour and
      // still read as uncertain at a glance.
      map.addLayer({
        id: LAYERS.hatch,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": "hexes",
        filter: UNCERTAIN,
        paint: { "fill-pattern": HATCH_ID },
      });

      for (const layer of CLICKABLE) {
        map.on("click", layer, (event: MapLayerMouseEvent) => {
          // Tile feature properties are untyped by definition; narrow before use.
          const properties: unknown = event.features?.[0]?.properties;
          if (properties && typeof properties === "object" && "h3" in properties) {
            const h3: unknown = properties.h3;
            if (typeof h3 === "string") onSelectRef.current(h3);
          }
        });
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, () => {
          map.getCanvas().style.cursor = "";
        });
      }
    });

    return () => {
      mapRef.current = null;
      map.remove();
      removeProtocol("pmtiles");
    };
  }, [tilesUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer(LAYERS.untrusted)) return;
    map.setLayoutProperty(
      LAYERS.untrusted,
      "visibility",
      showUntrusted ? "visible" : "none",
    );
  }, [showUntrusted]);

  return (
    <div className="relative h-full w-full">
      <div ref={container} className="h-full w-full" aria-label="Burden score map" />

      <SearchBox onGoTo={goTo} onSelect={onSelect} />

      {tilesUrl && <Legend showUntrusted={showUntrusted} onToggleUntrusted={setShowUntrusted} />}

      {tilesFailed && (
        <div
          role="alert"
          className="pointer-events-auto absolute inset-x-3 top-20 z-20 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 shadow-lg sm:inset-x-auto sm:right-3 sm:w-80"
        >
          <p className="font-semibold">The score layer did not load.</p>
          <p className="mt-0.5 text-xs">
            The basemap below is fine, so nothing here is scored. Usually the tile
            archive is unreachable, or its bucket is not sending CORS headers for
            this origin.
          </p>
        </div>
      )}
    </div>
  );
}
