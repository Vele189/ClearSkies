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

import type { Place } from "../lib/geocode.ts";
import {
  FILL_COLOR,
  HATCH_IMAGE_ID,
  hatchFilter,
  hatchImage,
  visibilityFilter,
} from "../lib/ramp.ts";
import Legend from "./Legend.tsx";
import SearchBox from "./SearchBox.tsx";

const DEFAULT_BASEMAP = "https://tiles.openfreemap.org/styles/positron";

// Louisiana, roughly. Phase 2 fits these to the scored extent instead.
const CENTER: [number, number] = [-91.5, 30.6];
const ZOOM = 6.6;

const SOURCE_ID = "clearskies-hexes";
const FILL_LAYER_ID = "clearskies-hex-fill";
const HATCH_LAYER_ID = "clearskies-hex-hatch";
const OUTLINE_LAYER_ID = "clearskies-hex-outline";

/** MapLibre merges an error's context object into the event, so a tile failure
 *  arrives carrying the source it came from. The published type does not
 *  describe that merge, hence the narrowing rather than a property access. */
function sourceOf(event: unknown): string | null {
  if (event && typeof event === "object" && "sourceId" in event) {
    const sourceId: unknown = event.sourceId;
    if (typeof sourceId === "string") return sourceId;
  }
  return null;
}

interface Props {
  onSelect: (h3: string) => void;
}

export default function MapView({ onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  const [ready, setReady] = useState(false);
  /** The basemap style itself failed. Nothing will render, so this one takes
   *  over the viewport rather than sitting in a corner of a blank screen. */
  const [fatal, setFatal] = useState<string | null>(null);
  /** The hex tiles failed but the basemap is up. The reader still has a usable
   *  map, so this is a notice and not a takeover. */
  const [tileError, setTileError] = useState(false);
  const [showInsufficient, setShowInsufficient] = useState(false);

  // Held in a ref so the map effect below can stay keyed to [] and not tear
  // down and rebuild the map every time the parent re-renders a new callback.
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

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

    const tilesUrl = import.meta.env.VITE_TILES_URL;

    // A style that never loads leaves a grey rectangle with no explanation,
    // which is the blank screen this ticket exists to rule out. MapLibre
    // reports both style and tile failures through the same event, so they are
    // separated by the source the failure is attributed to.
    map.on("error", (event) => {
      if (sourceOf(event) === SOURCE_ID) {
        setTileError(true);
        return;
      }
      // Recorded, not yet shown. A sprite or glyph 404 raises this too and is
      // survivable, so the overlay is gated on `load` never arriving.
      setFatal("The basemap could not be loaded.");
    });

    map.on("load", () => {
      setReady(true);
      setFatal(null);

      if (!tilesUrl) return; // No archive to point at until CS-207.

      const hatch = hatchImage();
      if (!map.hasImage(HATCH_IMAGE_ID)) map.addImage(HATCH_IMAGE_ID, hatch);

      map.addSource(SOURCE_ID, { type: "vector", url: `pmtiles://${tilesUrl}` });

      map.addLayer({
        id: FILL_LAYER_ID,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": "hexes",
        filter: visibilityFilter(false),
        paint: { "fill-color": FILL_COLOR, "fill-opacity": 0.75 },
      });

      // Drawn over the fill rather than in place of it, so a low-confidence hex
      // keeps the colour that says how burdened it is and gains the texture
      // that says how sure we are. Section 12 asks for hatching specifically:
      // fading the fill instead would read as a lower score.
      map.addLayer({
        id: HATCH_LAYER_ID,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": "hexes",
        filter: hatchFilter(false),
        paint: { "fill-pattern": HATCH_IMAGE_ID, "fill-opacity": 0.9 },
      });

      map.addLayer({
        id: OUTLINE_LAYER_ID,
        type: "line",
        source: SOURCE_ID,
        "source-layer": "hexes",
        filter: visibilityFilter(false),
        paint: { "line-color": "rgba(0,0,0,0.10)", "line-width": 0.5 },
      });

      map.on("click", FILL_LAYER_ID, (event: MapLayerMouseEvent) => {
        // Tile feature properties are untyped by definition; narrow before use.
        const properties: unknown = event.features?.[0]?.properties;
        if (properties && typeof properties === "object" && "h3" in properties) {
          const h3: unknown = properties.h3;
          if (typeof h3 === "string") onSelectRef.current(h3);
        }
      });
      map.on("mouseenter", FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = "";
      });
    });

    return () => {
      mapRef.current = null;
      map.remove();
      removeProtocol("pmtiles");
    };
  }, []);

  // The toggle drives the filters rather than a layer rebuild, so flipping it
  // is a repaint and not a re-fetch of every tile in view.
  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer(FILL_LAYER_ID)) return;
    map.setFilter(FILL_LAYER_ID, visibilityFilter(showInsufficient));
    map.setFilter(OUTLINE_LAYER_ID, visibilityFilter(showInsufficient));
    map.setFilter(HATCH_LAYER_ID, hatchFilter(showInsufficient));
  }, [showInsufficient, ready]);

  // Only a failure that stopped the map from ever loading is worth taking the
  // viewport for. Everything else leaves the reader a map they can still use.
  const blocked = ready ? null : fatal;

  const handlePick = useCallback((place: Place) => {
    mapRef.current?.flyTo({ center: place.center, zoom: 11, essential: true });
  }, []);

  return (
    <div className="relative h-full w-full">
      <div ref={container} className="h-full w-full" aria-label="Burden score map" />

      {!blocked && (
        <>
          <SearchBox onPick={handlePick} />
          <Legend
            showInsufficient={showInsufficient}
            onShowInsufficientChange={setShowInsufficient}
          />
        </>
      )}

      {!ready && !blocked && (
        <div
          role="status"
          className="absolute inset-0 z-20 flex items-center justify-center bg-slate-50 text-sm text-slate-500"
        >
          Loading map…
        </div>
      )}

      {blocked && (
        <div
          role="alert"
          className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-slate-50 px-6 text-center"
        >
          <p className="text-sm text-slate-700">{blocked}</p>
          <p className="max-w-sm text-xs text-slate-500">
            Scores are still available through the API. Reloading is worth trying; if it keeps
            failing the basemap host is likely down.
          </p>
          <button
            type="button"
            onClick={() => {
              window.location.reload();
            }}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
          >
            Reload
          </button>
        </div>
      )}

      {tileError && !blocked && (
        <div
          role="alert"
          className="pointer-events-auto absolute top-2 right-14 z-10 max-w-xs rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow-sm sm:top-3"
        >
          Hex scores could not be loaded, so the map is showing the basemap only. This is a
          loading failure, not an absence of burden.
        </div>
      )}
    </div>
  );
}
