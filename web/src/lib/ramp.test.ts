import { describe, expect, it } from "vitest";

import {
  CONFIDENCE,
  RAMP,
  TRUSTED,
  UNCERTAIN,
  UNSCORED,
  UNSCORED_COLOR,
  UNTRUSTED,
  bandFor,
  fillColor,
  hatchImage,
} from "./ramp.ts";

/** Evaluate one of the map's filter expressions the way MapLibre would.
 *
 *  Small on purpose: it understands only the handful of operators these filters
 *  use, which is enough to assert that a feature lands in exactly one band and
 *  far less machinery than running a real map. */
function evaluate(expression: unknown, properties: Record<string, unknown>): boolean {
  const [op, ...args] = expression as [string, ...unknown[]];

  switch (op) {
    case "all":
      return args.every((arg) => evaluate(arg, properties));
    case "any":
      return args.some((arg) => evaluate(arg, properties));
    case "!":
      return !evaluate(args[0], properties);
    case "has":
      return Object.prototype.hasOwnProperty.call(properties, args[0] as string);
    case ">=":
    case "<": {
      const left = value(args[0], properties);
      const right = value(args[1], properties);
      return op === ">=" ? left >= right : left < right;
    }
    default:
      throw new Error(`unsupported operator ${op}`);
  }
}

function value(node: unknown, properties: Record<string, unknown>): number {
  if (typeof node === "number") return node;
  const [op, ...args] = node as [string, ...unknown[]];
  if (op === "get") return properties[args[0] as string] as number;
  if (op === "coalesce") {
    for (const arg of args) {
      const resolved = value(arg, properties);
      if (resolved !== undefined && resolved !== null && !Number.isNaN(resolved)) {
        return resolved;
      }
    }
  }
  throw new Error(`unsupported value ${op}`);
}

const BANDS = { UNSCORED, TRUSTED, UNCERTAIN, UNTRUSTED };

function bandsMatching(properties: Record<string, unknown>): string[] {
  return Object.entries(BANDS)
    .filter(([, expression]) => evaluate(expression, properties))
    .map(([name]) => name);
}

describe("the ramp", () => {
  it("runs from light to dark so lightness carries the information", () => {
    // The property that makes ColorBrewer's sequential schemes colourblind-safe
    // and that also survives being printed in greyscale, which matters for a
    // tool whose output gets attached to a public comment.
    const luminance = RAMP.map(({ color }) => {
      const [r, g, b] = [1, 3, 5].map((at) => parseInt(color.slice(at, at + 2), 16));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    });

    expect(luminance).toEqual([...luminance].sort((a, b) => b - a));
  });

  it("has a stop at the top decile the validation protocol gates on", () => {
    expect(RAMP.map((stop) => stop.at)).toContain(90);
  });

  it("ramps over the percentile and not the raw score", () => {
    // Methodology section 10: the raw distribution is heavily right-skewed, so
    // a linear ramp on it would render most of the state indistinguishable.
    expect(JSON.stringify(fillColor)).toContain('"percentile"');
    expect(JSON.stringify(fillColor)).not.toContain('"score"');
  });
});

describe("the confidence bands", () => {
  it("puts a well-measured hex in exactly one band", () => {
    expect(bandsMatching({ percentile: 95, confidence: 0.9 })).toEqual(["TRUSTED"]);
  });

  it("treats moderate confidence the same as high, per section 12", () => {
    expect(bandsMatching({ percentile: 50, confidence: CONFIDENCE.moderate })).toEqual([
      "TRUSTED",
    ]);
  });

  it("hatches the band just below moderate", () => {
    expect(bandsMatching({ percentile: 50, confidence: 0.59 })).toEqual(["UNCERTAIN"]);
    expect(bandsMatching({ percentile: 50, confidence: CONFIDENCE.insufficient })).toEqual([
      "UNCERTAIN",
    ]);
  });

  it("puts an untrusted hex in the band that is hidden by default", () => {
    expect(bandsMatching({ percentile: 99, confidence: 0.39 })).toEqual(["UNTRUSTED"]);
  });

  it("keeps an unscored hex off the colour ramp entirely", () => {
    // Running a missing percentile through the ramp as zero would paint a cell
    // nobody measured as the cleanest in Louisiana.
    expect(bandsMatching({ no_score_reason: "low_population" })).toEqual(["UNSCORED"]);
  });

  it("draws a hex whose confidence was never computed rather than hiding it", () => {
    // A run from before CS-205 has scores and no confidence. Treating absent
    // confidence as zero would blank the map.
    expect(bandsMatching({ percentile: 70 })).toEqual(["TRUSTED"]);
  });
});

describe("bandFor", () => {
  it("names the bands at section 12's boundaries", () => {
    expect(bandFor(0.8)).toBe("high");
    expect(bandFor(0.79)).toBe("moderate");
    expect(bandFor(0.6)).toBe("moderate");
    expect(bandFor(0.59)).toBe("low");
    expect(bandFor(0.4)).toBe("low");
    expect(bandFor(0.39)).toBe("insufficient");
  });

  it("says so when there is no confidence rather than guessing one", () => {
    expect(bandFor(null)).toBe("unknown");
    expect(bandFor(undefined)).toBe("unknown");
  });
});

describe("the hatch pattern", () => {
  it("is an RGBA bitmap MapLibre can take as a fill pattern", () => {
    const hatch = hatchImage(8);

    expect(hatch.width).toBe(8);
    expect(hatch.data).toHaveLength(8 * 8 * 4);
  });

  it("is mostly transparent, so the colour underneath still reads", () => {
    const hatch = hatchImage(8);
    const opaque = [...hatch.data].filter((_, index) => index % 4 === 3).filter(Boolean);

    expect(opaque.length).toBeGreaterThan(0);
    expect(opaque.length).toBeLessThan(8 * 8 * 0.5);
  });
});

describe("the unscored colour", () => {
  it("is not a colour on the ramp", () => {
    expect(RAMP.map((stop) => stop.color)).not.toContain(UNSCORED_COLOR);
  });
});
