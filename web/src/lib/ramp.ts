/** Choropleth ramp, confidence-band treatment, and the MapLibre expressions
 *  built from them. The map and the legend both read this module, so a swatch
 *  in the legend is the same colour the tile is painted with by construction
 *  rather than by two lists being kept in step by hand.
 *
 *  Ramp and band treatment are specified in `docs/frontend.md`, which carries
 *  the reasoning. Bands themselves are methodology, not styling: the cut points
 *  come from `docs/methodology.md` section 12 and must not be changed here.
 */

import type { ExpressionSpecification, FilterSpecification } from "maplibre-gl";

import type { ConfidenceBand } from "./types.ts";

/** ColorBrewer YlOrRd, 6-class.
 *
 *  Chosen because it is monotone in lightness across the whole ramp, from
 *  L* 98 at the pale end to L* 35 at the dark end. That is the property that
 *  makes it readable under every form of colour vision deficiency including
 *  achromatopsia: strip the hue entirely and it degrades to a legible
 *  greyscale ramp. Hue is carrying emphasis here, not information.
 *
 *  Direction follows the convention a reader already has for burden maps:
 *  darker and hotter is worse. A perceptually uniform ramp such as viridis
 *  is equally colourblind-safe but puts bright yellow at the high end, which
 *  reads as "good" to anyone who has not consulted the legend.
 */
export const RAMP_COLORS = [
  "#ffffb2",
  "#fed976",
  "#feb24c",
  "#fd8d3c",
  "#f03b20",
  "#bd0026",
] as const;

/** Lower edge of each class above the first, as a statewide percentile.
 *
 *  Even 20-point classes up to the 80th, then a split at the 90th. The top
 *  decile is where the pre-registered validation criterion lives
 *  (methodology section 13.2), so a reader has to be able to see it as its
 *  own class rather than inferring it from the top fifth.
 */
export const RAMP_BREAKS = [20, 40, 60, 80, 90] as const;

/** Hexes the pipeline declined to score. Not a step on the ramp: a hex with no
 *  score is not a low-burden hex, and colouring it at the pale end would say
 *  exactly that. Neutral grey, its own legend entry. */
export const NO_SCORE_COLOR = "#d9d9d9";

export interface LegendClass {
  color: string;
  /** Inclusive lower edge as a statewide percentile. */
  from: number;
  /** Exclusive upper edge, except the top class which includes 100. */
  to: number;
  label: string;
}

export const LEGEND_CLASSES: LegendClass[] = RAMP_COLORS.map((color, i) => {
  const from = i === 0 ? 0 : RAMP_BREAKS[i - 1];
  const to = i === RAMP_COLORS.length - 1 ? 100 : RAMP_BREAKS[i];
  return { color, from, to, label: `${from}–${to}` };
});

/** Bands whose fill is hatched rather than solid. `unknown` is here on purpose:
 *  a tile that carries no confidence attribute at all is an archive defect, and
 *  drawing it as confident would be the one failure mode section 12 is written
 *  to prevent. It reads as uncertain until the archive says otherwise. */
const HATCHED_BANDS = ["low", "unknown"] as const;

/** The bands as the map knows them. `unknown` is not a methodology band: it is
 *  what a tile that states neither a band nor a confidence value resolves to. */
export type MapBand = ConfidenceBand | "unknown";

/** Band as the tile reports it, falling back to deriving it from the raw
 *  confidence value, and finally to `unknown`. Cut points are section 12's. */
export const BAND: ExpressionSpecification = [
  "coalesce",
  ["get", "confidence_band"],
  [
    "case",
    ["has", "confidence"],
    ["step", ["get", "confidence"], "insufficient", 0.4, "low", 0.6, "moderate", 0.8, "high"],
    "unknown",
  ],
];

/** Stepped rather than interpolated so that every colour on the map appears in
 *  the legend. A continuous ramp asks the reader to interpolate by eye between
 *  two swatches, which they cannot do accurately and should not have to. */
export const FILL_COLOR: ExpressionSpecification = [
  "case",
  ["==", ["typeof", ["get", "percentile"]], "number"],
  [
    "step",
    ["get", "percentile"],
    RAMP_COLORS[0],
    ...RAMP_BREAKS.flatMap((brk, i) => [brk, RAMP_COLORS[i + 1]]),
  ],
  NO_SCORE_COLOR,
];

/** Section 12 treatment: high and moderate at full opacity, low hatched, and
 *  insufficient hidden behind a toggle. Opacity is deliberately *not* used to
 *  express confidence — a washed-out fill reads as a lower score, which
 *  conflates how certain we are with how bad it is. Hatching does not. */
export function visibilityFilter(showInsufficient: boolean): FilterSpecification {
  const hidden: MapBand[] = showInsufficient ? [] : ["insufficient"];
  return ["!", ["in", BAND, ["literal", hidden]]];
}

export function hatchFilter(showInsufficient: boolean): FilterSpecification {
  // An insufficient hex, once the reader has asked to see it, is hatched too.
  const hatched: MapBand[] = showInsufficient
    ? [...HATCHED_BANDS, "insufficient"]
    : [...HATCHED_BANDS];
  return ["in", BAND, ["literal", hatched]];
}

export const HATCH_IMAGE_ID = "clearskies-hatch";

/** 45° hatch, drawn once and registered with the map as an image so the fill
 *  layer can reference it. Returned as raw RGBA rather than a canvas so the
 *  shape of it is testable without a DOM.
 *
 *  Dark lines on transparent: the pattern overlays the choropleth fill rather
 *  than replacing it, so a low-confidence hex keeps the colour that says how
 *  burdened it is while gaining the texture that says how sure we are.
 */
export function hatchImage(size = 8, lineWidth = 1.5): ImageData | { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      // Distance along the anti-diagonal to the nearest line, measured the
      // short way round so the pattern tiles seamlessly at the tile edge.
      const m = (x + y) % size;
      const on = Math.min(m, size - m) < lineWidth;
      const i = (y * size + x) * 4;
      data[i] = 40;
      data[i + 1] = 40;
      data[i + 2] = 40;
      data[i + 3] = on ? 170 : 0;
    }
  }
  return { width: size, height: size, data };
}
