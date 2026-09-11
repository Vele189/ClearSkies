/**
 * The choropleth ramp and the confidence treatment, in one place.
 *
 * The map and the legend must agree or the legend is a lie, so both read this
 * file rather than each holding their own copy of the colours.
 *
 * **The ramp is ColorBrewer YlOrRd.** Sequential, published as colourblind-safe,
 * and monotonic in luminance, which is the property that matters twice over
 * here. It survives deuteranopia and protanopia because the lightness ordering
 * carries the information rather than the hue, and it survives being printed in
 * greyscale, which a tool whose output is meant to be attached to a public
 * comment or handed to a reporter should not ignore.
 *
 * **It ramps over the percentile, not the raw score.** Methodology section 10:
 * the raw distribution is heavily right-skewed and a linear ramp on it would
 * render most of the state indistinguishable. The extra stop at 90 is the top
 * decile, which is the threshold the validation protocol in section 13 gates on,
 * so the band the project makes claims about is the band the eye can find.
 *
 * **An unscored hexagon is not on the ramp at all.** It takes a neutral grey.
 * Feeding a missing percentile through the ramp as 0 would paint a cell nobody
 * measured as the cleanest in Louisiana, which is the zero-for-missing failure
 * section 11 spends a page ruling out, arriving in the render layer by the back
 * door. Grey says "no score, and the panel will tell you why".
 *
 * **Confidence is drawn, not merely reported.** Section 12 fixes the treatment:
 * full opacity for high and moderate, a hatched fill for low, and the
 * insufficient band hidden behind a toggle rather than shown by default. A hex
 * the system does not trust should not be able to be read off the map as though
 * it were measured, and a hex that is merely uncertain should look uncertain
 * rather than be deleted.
 *
 * Still to be signed off by Lead, per CS-210.
 */

import type { ExpressionSpecification } from "maplibre-gl";

/** ColorBrewer YlOrRd, 6-class, with the top stop at the decile section 13 gates on. */
export const RAMP: readonly { readonly at: number; readonly color: string }[] = [
  { at: 0, color: "#ffffb2" },
  { at: 25, color: "#fed976" },
  { at: 50, color: "#feb24c" },
  { at: 75, color: "#fd8d3c" },
  { at: 90, color: "#f03b20" },
  { at: 100, color: "#bd0026" },
];

/** Hexes with no score. Deliberately off the ramp and deliberately drab. */
export const UNSCORED_COLOR = "#cbd5e1";

/** Section 12's bands, as the thresholds the map filters on. */
export const CONFIDENCE = {
  /** At or above this a hex draws at full opacity. */
  moderate: 0.6,
  /** Below this a hex is hidden unless the reader asks for it. */
  insufficient: 0.4,
} as const;

export const FULL_OPACITY = 0.78;

/** Colour by percentile. Only ever applied to features that have one. */
export const fillColor: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["get", "percentile"],
  ...RAMP.flatMap(({ at, color }) => [at, color] as const),
] as unknown as ExpressionSpecification;

/** Scored, and trusted enough to draw plainly: high or moderate. */
export const TRUSTED: ExpressionSpecification = [
  "all",
  ["has", "percentile"],
  [">=", ["coalesce", ["get", "confidence"], 1], CONFIDENCE.moderate],
];

/** Scored, but low confidence. Drawn hatched so it reads as uncertain. */
export const UNCERTAIN: ExpressionSpecification = [
  "all",
  ["has", "percentile"],
  [">=", ["coalesce", ["get", "confidence"], 1], CONFIDENCE.insufficient],
  ["<", ["coalesce", ["get", "confidence"], 1], CONFIDENCE.moderate],
];

/** Scored, but the system does not trust it. Hidden unless asked for. */
export const UNTRUSTED: ExpressionSpecification = [
  "all",
  ["has", "percentile"],
  ["<", ["coalesce", ["get", "confidence"], 1], CONFIDENCE.insufficient],
];

/** No score at all. Present in the tiles so the map can explain the hole. */
export const UNSCORED: ExpressionSpecification = ["!", ["has", "percentile"]];

/**
 * Which band a confidence value falls in, for the panel and the legend.
 *
 * Kept beside the map's thresholds so the words a reader sees and the treatment
 * they are looking at cannot drift apart.
 */
export function bandFor(confidence: number | null | undefined): string {
  if (confidence == null) return "unknown";
  if (confidence >= 0.8) return "high";
  if (confidence >= CONFIDENCE.moderate) return "moderate";
  if (confidence >= CONFIDENCE.insufficient) return "low";
  return "insufficient";
}

/**
 * A diagonal hatch, as an RGBA bitmap MapLibre can use as a fill pattern.
 *
 * Generated rather than shipped as a file so it cannot go missing from a build,
 * and so the map does not need a sprite sheet for one texture.
 */
export function hatchImage(size = 8): { width: number; height: number; data: Uint8Array } {
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const offset = (y * size + x) * 4;
      // Two thin diagonals per tile, so the pattern reads as texture at a
      // glance without swallowing the colour underneath it.
      const on = (x + y) % 4 === 0;
      data[offset] = 30;
      data[offset + 1] = 41;
      data[offset + 2] = 59;
      data[offset + 3] = on ? 170 : 0;
    }
  }
  return { width: size, height: size, data };
}
