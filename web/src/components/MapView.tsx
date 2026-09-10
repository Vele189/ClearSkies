import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  addProtocol,
  removeProtocol,
} from "maplibre-gl";
import type { ExpressionSpecification, MapLayerMouseEvent } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { useEffect, useRef } from "react";

const DEFAULT_BASEMAP = "https://tiles.openfreemap.org/styles/positron";

// Louisiana, roughly. Phase 2 fits these to the scored extent instead.
const CENTER: [number, number] = [-91.5, 30.6];
const ZOOM = 6.6;

const SOURCE_ID = "clearskies-hexes";
const LAYER_ID = "clearskies-hex-fill";

/** Sequential ramp over the statewide score percentile, not the raw score.
 *  The raw distribution is heavily right-skewed, so a linear ramp on it would
 *  render most of the state indistinguishable. See methodology section 10. */
const FILL_COLOR: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["coalesce", ["get", "percentile"], 0],
  0,
  "#f7f7f7",
  25,
  "#fddbc7",
  50,
  "#f4a582",
  75,
  "#d6604d",
  90,
  "#b2182b",
  100,
  "#67001f",
];

/** Hexes the pipeline does not trust are hatched down rather than hidden,
 *  so a gap in coverage reads as uncertainty and not as clean air. */
const FILL_OPACITY: ExpressionSpecification = [
  "case",
  ["<", ["coalesce", ["get", "confidence"], 1], 0.4],
  0.15,
  ["<", ["coalesce", ["get", "confidence"], 1], 0.6],
  0.4,
  0.75,
];

interface Props {
  onSelect: (h3: string) => void;
}

export default function MapView({ onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

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

    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-left");

    const tilesUrl = import.meta.env.VITE_TILES_URL;

    map.on("load", () => {
      if (!tilesUrl) return; // Phase 1 has not produced tiles yet.

      map.addSource(SOURCE_ID, { type: "vector", url: `pmtiles://${tilesUrl}` });
      map.addLayer({
        id: LAYER_ID,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": "hexes",
        paint: {
          "fill-color": FILL_COLOR,
          "fill-opacity": FILL_OPACITY,
          "fill-outline-color": "rgba(0,0,0,0.08)",
        },
      });

      map.on("click", LAYER_ID, (event: MapLayerMouseEvent) => {
        const h3 = event.features?.[0]?.properties?.h3;
        if (typeof h3 === "string") onSelectRef.current(h3);
      });
      map.on("mouseenter", LAYER_ID, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", LAYER_ID, () => {
        map.getCanvas().style.cursor = "";
      });
    });

    return () => {
      map.remove();
      removeProtocol("pmtiles");
    };
  }, []);

  return <div ref={container} className="h-full w-full" aria-label="Burden score map" />;
}
