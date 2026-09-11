import { createExpression, featureFilter } from "@maplibre/maplibre-gl-style-spec";
import type { FilterSpecification } from "maplibre-gl";
import { describe, expect, it } from "vitest";

import {
  FILL_COLOR,
  LEGEND_CLASSES,
  NO_SCORE_COLOR,
  RAMP_BREAKS,
  RAMP_COLORS,
  hatchFilter,
  hatchImage,
  visibilityFilter,
} from "./ramp.ts";

/** Relative luminance, sRGB. Enough to assert the ordering the ramp choice
 *  rests on; it is not trying to be a colour science library. */
function luminance(hex: string): number {
  const channel = (start: number) => {
    const v = parseInt(hex.slice(start, start + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

describe("ramp", () => {
  it("is monotonically darker as burden rises", () => {
    // This is the whole colourblind-safety argument. If it ever stops holding,
    // the ramp no longer degrades to a readable greyscale and the claim in
    // docs/frontend.md is false.
    const lums = RAMP_COLORS.map(luminance);
    for (let i = 1; i < lums.length; i++) {
      expect(lums[i]).toBeLessThan(lums[i - 1]);
    }
  });

  it("gives every class a visible step of lightness", () => {
    const lums = RAMP_COLORS.map(luminance);
    for (let i = 1; i < lums.length; i++) {
      expect(lums[i - 1] - lums[i]).toBeGreaterThan(0.02);
    }
  });

  it("keeps the not-scored colour off the ramp", () => {
    expect(RAMP_COLORS).not.toContain(NO_SCORE_COLOR);
  });

  it("covers 0 to 100 with no gap or overlap", () => {
    expect(LEGEND_CLASSES[0].from).toBe(0);
    expect(LEGEND_CLASSES[LEGEND_CLASSES.length - 1].to).toBe(100);
    for (let i = 1; i < LEGEND_CLASSES.length; i++) {
      expect(LEGEND_CLASSES[i].from).toBe(LEGEND_CLASSES[i - 1].to);
    }
  });

  it("breaks out the top decile as its own class", () => {
    // Methodology section 13.2 pre-registers a top-decile criterion, so the
    // reader has to be able to see the top decile without inferring it.
    expect(RAMP_BREAKS).toContain(90);
    expect(LEGEND_CLASSES.some((c) => c.from === 90 && c.to === 100)).toBe(true);
  });

  it("has one legend swatch per map colour", () => {
    expect(LEGEND_CLASSES.map((c) => c.color)).toEqual([...RAMP_COLORS]);
  });
});

/** Runs a filter the way MapLibre does, so these assertions are about what the
 *  map actually draws rather than about the shape of an expression literal. */
function matches(filter: FilterSpecification, properties: Record<string, unknown>): boolean {
  const compiled = featureFilter(filter, "layers[0].filter");
  return compiled.filter(
    { zoom: 8 },
    { type: 1, properties } as never,
    undefined as never,
  );
}

/** The band cut points are methodology, not styling. These values sit either
 *  side of each boundary in section 12's table. */
const SAMPLES = {
  high: { confidence: 0.95 },
  highEdge: { confidence: 0.8 },
  moderate: { confidence: 0.7 },
  moderateEdge: { confidence: 0.6 },
  low: { confidence: 0.5 },
  lowEdge: { confidence: 0.4 },
  insufficient: { confidence: 0.39 },
  unknown: {},
  labelled: { confidence_band: "insufficient", confidence: 0.95 },
};

describe("confidence filters", () => {
  it("shows high, moderate and low by default and hides insufficient", () => {
    const filter = visibilityFilter(false);
    expect(matches(filter, SAMPLES.high)).toBe(true);
    expect(matches(filter, SAMPLES.moderate)).toBe(true);
    expect(matches(filter, SAMPLES.low)).toBe(true);
    expect(matches(filter, SAMPLES.insufficient)).toBe(false);
  });

  it("reveals insufficient hexes when the toggle is on", () => {
    expect(matches(visibilityFilter(true), SAMPLES.insufficient)).toBe(true);
  });

  it("places every band boundary where section 12 puts it", () => {
    const shown = visibilityFilter(false);
    // 0.40 is the bottom of Low, so it is drawn; 0.39 is Insufficient.
    expect(matches(shown, SAMPLES.lowEdge)).toBe(true);
    expect(matches(shown, SAMPLES.insufficient)).toBe(false);

    const hatched = hatchFilter(false);
    // 0.60 is the bottom of Moderate, so it is solid, not hatched.
    expect(matches(hatched, SAMPLES.moderateEdge)).toBe(false);
    expect(matches(hatched, SAMPLES.low)).toBe(true);
    // 0.80 is the bottom of High.
    expect(matches(hatched, SAMPLES.highEdge)).toBe(false);
  });

  it("hatches the low band and leaves high and moderate solid", () => {
    const filter = hatchFilter(false);
    expect(matches(filter, SAMPLES.low)).toBe(true);
    expect(matches(filter, SAMPLES.moderate)).toBe(false);
    expect(matches(filter, SAMPLES.high)).toBe(false);
  });

  it("hatches a tile that carries no confidence attribute at all", () => {
    // An archive missing the attribute is a defect, and drawing those hexes as
    // confident is the failure section 12 exists to prevent.
    expect(matches(hatchFilter(false), SAMPLES.unknown)).toBe(true);
    expect(matches(visibilityFilter(false), SAMPLES.unknown)).toBe(true);
  });

  it("hatches insufficient hexes once they are revealed", () => {
    expect(matches(hatchFilter(true), SAMPLES.insufficient)).toBe(true);
  });

  it("trusts the band the archive states over the value it derives", () => {
    // CS-207 writes both. If they disagree the stated band wins, so a band
    // correction in the pipeline does not need a frontend release.
    expect(matches(visibilityFilter(false), SAMPLES.labelled)).toBe(false);
  });
});

/** Evaluates the paint expression the way the renderer does and returns the
 *  colour as a hex string, so these assertions read against the ramp table. */
function fillColor(properties: Record<string, unknown>): string {
  const compiled = createExpression(FILL_COLOR, "layers[0].paint.fill-color", {
    type: "color",
    "property-type": "data-driven",
    expression: { interpolated: true, parameters: ["zoom", "feature"] },
  } as never);
  if (compiled.result === "error") throw new Error("fill-color does not compile");

  const color: unknown = compiled.value.evaluate({ zoom: 8 } as never, { properties } as never);
  const { r, g, b } = color as { r: number; g: number; b: number };
  const byte = (v: number) =>
    Math.round(v * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${byte(r)}${byte(g)}${byte(b)}`;
}

describe("fill colour", () => {
  it("paints each percentile into its legend class", () => {
    for (const cls of LEGEND_CLASSES) {
      // A value just inside the class, and the class's own lower edge.
      expect(fillColor({ percentile: cls.from })).toBe(cls.color);
      expect(fillColor({ percentile: cls.to - 0.5 })).toBe(cls.color);
    }
  });

  it("paints the very top of the range in the top-decile colour", () => {
    expect(fillColor({ percentile: 100 })).toBe(RAMP_COLORS[RAMP_COLORS.length - 1]);
  });

  it("paints an unscored hex neutral rather than pale", () => {
    // A hex with no score is not a low-burden hex. Colouring it at the pale end
    // of the ramp would say exactly that, which methodology section 11 forbids.
    expect(fillColor({ percentile: null })).toBe(NO_SCORE_COLOR);
    expect(fillColor({ no_score_reason: "low_population" })).toBe(NO_SCORE_COLOR);
    expect(fillColor({ percentile: null })).not.toBe(RAMP_COLORS[0]);
  });
});

describe("hatchImage", () => {
  it("produces a square RGBA buffer", () => {
    const image = hatchImage(8);
    expect(image.width).toBe(8);
    expect(image.height).toBe(8);
    expect(image.data).toHaveLength(8 * 8 * 4);
  });

  it("leaves most of the cell transparent so the fill colour reads through", () => {
    const image = hatchImage(8);
    let opaque = 0;
    for (let i = 3; i < image.data.length; i += 4) {
      if (image.data[i] > 0) opaque++;
    }
    expect(opaque).toBeGreaterThan(0);
    expect(opaque / (8 * 8)).toBeLessThan(0.5);
  });

  it("tiles seamlessly across the cell edge", () => {
    // A line entering the right edge at row y has to leave the left edge at
    // row y+1, or the pattern shows a seam at every tile boundary.
    const size = 8;
    const image = hatchImage(size);
    const alpha = (x: number, y: number) => image.data[(y * size + x) * 4 + 3];
    for (let y = 0; y < size - 1; y++) {
      expect(alpha(size - 1, y)).toBe(alpha(size - 2, y + 1));
    }
  });
});
