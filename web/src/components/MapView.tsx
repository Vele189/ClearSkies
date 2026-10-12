import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  addProtocol,
  removeProtocol,
} from "maplibre-gl";
import type { GeoJSONSource, MapLayerMouseEvent } from "maplibre-gl";
import { PMTiles, Protocol } from "pmtiles";
import { useCallback, useEffect, useRef, useState } from "react";

import { getStates } from "../lib/api.ts";
import type { Place } from "../lib/geocode.ts";
import {
  FILL_COLOR,
  FILL_OPACITY,
  HATCH_IMAGE_ID,
  hatchFilter,
  hatchImage,
  visibilityFilter,
} from "../lib/ramp.ts";
import Legend from "./Legend.tsx";
import SearchBox from "./SearchBox.tsx";

const DEFAULT_BASEMAP = "https://tiles.openfreemap.org/styles/positron";

// Where the map opens before it knows what it is showing.
//
// Louisiana, roughly, and only until the archive's own header says otherwise:
// the view is fitted to the scored extent below. These two remain because a
// deployment with no archive configured still has to put the camera somewhere,
// and a reader who sees the pilot state while the banner explains that no tiles
// are loaded is better served than one looking at the middle of the ocean.
const CENTER: [number, number] = [-91.5, 30.6];
const ZOOM = 6.6;

//: Breathing room around the scored extent, in pixels.
const FIT_PADDING = 48;

//: Above this zoom the hexes themselves are the answer, so the markers go.
//: The archive starts at z6, so the two ranges overlap, and a reader
//: zooming in sees the cells appear under the ring before the ring goes.
const MARKER_MAX_ZOOM = 7.5;

//: Slate, chosen to be nothing like the ramp.
//:
//: docs/frontend.md section 2 gives the map one colour scale, YlOrRd, and every
//: colour on it means a burden class. A marker drawn anywhere near that range
//: would be read as data. This is outside it in hue and in saturation, so it
//: reads as furniture.
const MARKER_COLOR = "#334155";

/** A state's extent, read back off a clicked marker.
 *
 *  Stored as four numbers rather than one array: a GeoJSON property holding an
 *  array comes back from a feature as a JSON string on some paths and an array
 *  on others, and four numbers are the same on all of them.
 */
function extentOf(
  properties: Record<string, unknown> | null | undefined,
): [[number, number], [number, number]] | null {
  if (!properties) return null;
  const { west, south, east, north } = properties;
  if (
    typeof west !== "number" ||
    typeof south !== "number" ||
    typeof east !== "number" ||
    typeof north !== "number"
  ) {
    return null;
  }
  return [
    [west, south],
    [east, north],
  ];
}

const SOURCE_ID = "clearskies-hexes";
const STATES_SOURCE_ID = "clearskies-states";
const STATES_CIRCLE_ID = "clearskies-state-circle";
const STATES_LABEL_ID = "clearskies-state-label";
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

    const states = new AbortController();

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

      // One PMTiles instance, shared with the protocol, so reading the header
      // does not open the archive a second time.
      const archive = new PMTiles(tilesUrl);
      protocol.add(archive);
      map.addSource(SOURCE_ID, { type: "vector", url: `pmtiles://${tilesUrl}` });

      // Frame what is actually scored, rather than the state this started as.
      //
      // The bounds come from the archive's header, which is metadata rather
      // than data: it is exact, it costs no tile reads, and it is right the
      // first time a second state is added without anybody editing a constant.
      // Two distant states fit to a view holding both, which is honest about
      // the coverage even though most of what it shows is between them.
      //
      // A header that will not load is not worth failing the map over. The
      // camera stays where it opened and the tile-failure notice, which is
      // driven by the source rather than by this, says what went wrong.
      void archive
        .getHeader()
        .then((header) => {
          if (map.getContainer() === null) return;
          map.fitBounds(
            [
              [header.minLon, header.minLat],
              [header.maxLon, header.maxLat],
            ],
            { padding: FIT_PADDING, duration: 0 },
          );
        })
        .catch(() => {
          /* keep CENTER/ZOOM; the notice below reports the archive itself */
        });

      map.addLayer({
        id: FILL_LAYER_ID,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": "hexes",
        filter: visibilityFilter(false),
        paint: { "fill-color": FILL_COLOR, "fill-opacity": FILL_OPACITY },
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

      // Where the scored states are, for the zoom levels that have no hexes.
      //
      // Below zoom 6 the archive has no tiles at all, so a reader who zooms out
      // to find the other states is looking at an empty basemap with nothing to
      // say that anywhere else was scored. These rings are what they aim at;
      // clicking one flies to that state's own extent.
      map.addSource(STATES_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: STATES_CIRCLE_ID,
        type: "circle",
        source: STATES_SOURCE_ID,
        maxzoom: MARKER_MAX_ZOOM,
        paint: {
          // Bigger where there is more to look at, by cell count on a log
          // scale: Louisiana has 171,725 cells to the District's 246, and a
          // radius proportional to that would put one of them off the screen.
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["log10", ["max", ["get", "cells"], 1]],
            2,
            7,
            6,
            18,
          ],
          "circle-color": MARKER_COLOR,
          "circle-opacity": 0.15,
          "circle-stroke-color": MARKER_COLOR,
          "circle-stroke-width": 2,
          "circle-stroke-opacity": 0.9,
        },
      });

      map.addLayer({
        id: STATES_LABEL_ID,
        type: "symbol",
        source: STATES_SOURCE_ID,
        maxzoom: MARKER_MAX_ZOOM,
        layout: {
          "text-field": ["get", "name"],
          "text-size": 12,
          "text-offset": [0, 1.6],
          "text-anchor": "top",
          "text-allow-overlap": false,
        },
        paint: {
          "text-color": MARKER_COLOR,
          // A halo, because the label sits over whatever the basemap has there
          // and a state name that cannot be read is a marker without a name.
          "text-halo-color": "#ffffff",
          "text-halo-width": 1.5,
        },
      });

      // Filled from the API rather than drawn from anything in this bundle.
      // A state's marker sits on the cells that were actually scored, and the
      // next state to arrive brings its own without a release here.
      //
      // A failure here is silent. The markers help a reader find their way at
      // low zoom, and a map that refused to draw because it could not
      // decorate itself would be worse than one without rings.
      void getStates(states.signal)
        .then((extents) => {
          const source = map.getSource<GeoJSONSource>(STATES_SOURCE_ID);
          if (!source) return;
          void source.setData({
            type: "FeatureCollection",
            features: extents.map((state) => ({
              type: "Feature" as const,
              geometry: { type: "Point" as const, coordinates: state.centroid },
              properties: {
                usps: state.usps,
                name: state.name,
                cells: state.cells,
                west: state.bounds[0],
                south: state.bounds[1],
                east: state.bounds[2],
                north: state.bounds[3],
              },
            })),
          });
        })
        .catch(() => {
          /* no rings; the hexes themselves are unaffected */
        });

      map.on("click", STATES_CIRCLE_ID, (event: MapLayerMouseEvent) => {
        const extent = extentOf(event.features?.[0]?.properties);
        if (extent) {
          map.fitBounds(extent, { padding: FIT_PADDING, duration: 600 });
        }
      });
      map.on("mouseenter", STATES_CIRCLE_ID, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", STATES_CIRCLE_ID, () => {
        map.getCanvas().style.cursor = "";
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
      states.abort();
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
  const blocked = contextLost
    ? "The map lost its graphics context and has stopped drawing."
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
              ? "The browser dropped the map's WebGL context, usually under memory pressure or a " +
                "graphics driver reset. Reloading gets a fresh one; if it recurs, check that " +
                "hardware acceleration is enabled."
              : "Scores are still available through the API. Reloading is worth trying; if it " +
                "keeps failing the basemap host is likely down."}
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
