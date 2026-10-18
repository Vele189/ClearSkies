import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  addProtocol,
  removeProtocol,
} from "maplibre-gl";
import type { MapLayerMouseEvent } from "maplibre-gl";
import { LocateFixed } from "lucide-react";
import { Protocol } from "pmtiles";
import { useCallback, useEffect, useRef, useState } from "react";

import type { Place } from "../lib/geocode.ts";
import { LOUISIANA_BOUNDS, MAX_BOUNDS, MIN_ZOOM } from "../lib/louisiana.ts";
import {
  FILL_COLOR,
  FILL_OPACITY_BY_SCORE,
  HATCH_IMAGE_ID,
  hatchFilter,
  hatchImage,
  outlineFilter,
  visibilityFilter,
} from "../lib/ramp.ts";
import Legend from "./Legend.tsx";
import SearchBox from "./SearchBox.tsx";

const DEFAULT_BASEMAP = "https://tiles.openfreemap.org/styles/positron";

/** Room left round Louisiana when the camera frames it, so the search box and
 *  the legend do not sit on top of a parish. On a phone the legend is
 *  collapsed and there is no room to give, so the frame is nearly edge to edge
 *  and the zoom floor decides the rest. */
function fitPadding(width: number) {
  return width >= 900
    ? { top: 72, bottom: 40, left: 300, right: 64 }
    : { top: 64, bottom: 56, left: 8, right: 8 };
}

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

/** The H3 index a rendered feature carries. Tile feature properties are
 *  untyped by definition, so this narrows rather than trusts them. */
function h3Of(properties: unknown): string | null {
  if (properties && typeof properties === "object" && "h3" in properties) {
    const h3: unknown = properties.h3;
    if (typeof h3 === "string") return h3;
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
  const [contextLost, setContextLost] = useState(false);

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

    // Locked to Louisiana: it opens framing the whole state, cannot be panned
    // past it, and cannot be zoomed out past the archive's first zoom, where
    // every hexagon would vanish and leave a map of the world.
    const map = new MapLibreMap({
      container: container.current,
      style: import.meta.env.VITE_BASEMAP_STYLE ?? DEFAULT_BASEMAP,
      bounds: LOUISIANA_BOUNDS,
      fitBoundsOptions: { padding: fitPadding(container.current.clientWidth) },
      maxBounds: MAX_BOUNDS,
      minZoom: MIN_ZOOM,
      renderWorldCopies: false,
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
      setFatal("The map couldn't load.");
    });

    // A lost context is not reported through map.on("error"). Without this the
    // canvas simply freezes after `load` has already fired, which leaves the
    // reader a map that looks live and is not — the failure mode the error
    // handler above exists to rule out, arriving by a door it does not watch.
    // Common on an integrated GPU when dev-mode remounts churn through
    // contexts, and survivable: a reload gets a fresh one.
    const canvas = map.getCanvas();
    const onContextLost = () => setContextLost(true);
    canvas.addEventListener("webglcontextlost", onContextLost);
    canvas.addEventListener("webglcontextrestored", () => setContextLost(false));

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
        paint: { "fill-color": FILL_COLOR, "fill-opacity": FILL_OPACITY_BY_SCORE },
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
        filter: outlineFilter(false),
        paint: { "line-color": "rgba(0,0,0,0.10)", "line-width": 0.5 },
      });

      map.on("click", FILL_LAYER_ID, (event: MapLayerMouseEvent) => {
        const h3 = h3Of(event.features?.[0]?.properties);
        if (h3) onSelectRef.current(h3);
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
      canvas.removeEventListener("webglcontextlost", onContextLost);
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
    map.setFilter(OUTLINE_LAYER_ID, outlineFilter(showInsufficient));
    map.setFilter(HATCH_LAYER_ID, hatchFilter(showInsufficient));
  }, [showInsufficient, ready]);

  // Only a failure that stopped the map from ever loading is worth taking the
  // viewport for. Everything else leaves the reader a map they can still use.
  const blocked = contextLost
    ? "The map has stopped drawing."
    : ready
      ? null
      : fatal;

  /** The selection waiting on a flight to finish, so a second pick can cancel
   *  the first rather than open two panels in turn. */
  const pendingPick = useRef<(() => void) | null>(null);

  // A search pick selects the hexagon under it, not only the view. Clicking is
  // otherwise the only way into a panel, and a reader on the keyboard would be
  // shown the right place and given no way to open it. The fill is queried at
  // the point once the flight has settled and its tiles have drawn, because
  // until then the hexagon there may not be rendered at all.
  const handlePick = useCallback((place: Place) => {
    const map = mapRef.current;
    if (!map) return;

    if (pendingPick.current) {
      map.off("moveend", pendingPick.current);
      map.off("idle", pendingPick.current);
    }
    // Ending any flight still under way before listening, because an
    // interrupted flight fires its own moveend, and this pick would otherwise
    // take that for its own arrival and select at the old position.
    map.stop();

    const select = () => {
      pendingPick.current = null;
      if (!map.getLayer(FILL_LAYER_ID)) return;
      const features = map.queryRenderedFeatures(map.project(place.center), {
        layers: [FILL_LAYER_ID],
      });
      const h3 = h3Of(features[0]?.properties);
      if (h3) onSelectRef.current(h3);
    };
    const settle = () => {
      if (map.areTilesLoaded()) {
        select();
      } else {
        pendingPick.current = select;
        map.once("idle", select);
      }
    };
    pendingPick.current = settle;
    map.once("moveend", settle);

    map.flyTo({ center: place.center, zoom: 11, essential: true });
  }, []);

  /** Back to the whole state, from wherever a search or a pan has left the
   *  reader. With the map locked this is the one view that is always right. */
  const showLouisiana = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    map.fitBounds(LOUISIANA_BOUNDS, { padding: fitPadding(map.getContainer().clientWidth) });
  }, []);

  return (
    <div className="relative h-full w-full">
      <div
        ref={container}
        role="region"
        className="h-full w-full"
        aria-label="Burden score map"
      />

      {!blocked && (
        <>
          <SearchBox onPick={handlePick} />
          {/* Under MapLibre's zoom buttons, and styled like them, so it reads as
              the third control of one group rather than a separate widget. */}
          <button
            type="button"
            onClick={showLouisiana}
            aria-label="Show all of Louisiana"
            title="Show all of Louisiana"
            className="pointer-events-auto absolute top-[5.25rem] right-2.5 z-10 flex size-[29px]
                       items-center justify-center rounded bg-white text-[#333]
                       shadow-[0_0_0_2px_rgba(0,0,0,0.1)] hover:bg-[#f2f2f2] sm:top-[5.875rem]"
          >
            <LocateFixed aria-hidden="true" className="size-4" />
          </button>
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
            {contextLost
              ? "This usually happens when the browser is short of memory. Reloading the page " +
                "normally fixes it."
              : "Try reloading the page. If it keeps happening, the map service may be down " +
                "for a while."}
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
          The pollution layer didn&apos;t load, so you&apos;re only seeing the background map.
          This is a loading problem. It doesn&apos;t mean there&apos;s no pollution.
        </div>
      )}
    </div>
  );
}
