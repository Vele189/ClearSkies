import { describe, expect, it } from "vitest";

import {
  bandReading,
  confidenceTerms,
  droppedGroups,
  isZeroInflated,
  leadsWithCaveat,
  productOfComponents,
  vintageFor,
  weakestTerm,
  weightedGroupMean,
} from "./score.ts";
import type { Confidence, GroupScore, IndicatorValue } from "./types.ts";

function group(over: Partial<GroupScore> = {}): GroupScore {
  return {
    group: "exposures",
    mean_percentile: 80,
    weight: 1.0,
    indicators_present: 4,
    indicators_required: 2,
    computable: true,
    ...over,
  };
}

function confidence(over: Partial<Confidence> = {}): Confidence {
  return {
    value: 0.72,
    band: "moderate",
    coverage: 0.9,
    recency: 0.8,
    spatial_support: 0.7,
    monitor_support: 0.5,
    nearest_monitor_km: 20,
    ...over,
  };
}

function indicator(over: Partial<IndicatorValue> = {}): IndicatorValue {
  return {
    id: "E1",
    name: "Air toxics cancer risk",
    group: "exposures",
    value: 42,
    unit: "risk per million",
    percentile: 91,
    source: "EPA AirToxScreen",
    observed: true,
    ...over,
  };
}

describe("weightedGroupMean", () => {
  it("weights the groups the way methodology section 10 does", () => {
    // PB_raw = (1.0 * 80 + 0.5 * 20) / 1.5
    const mean = weightedGroupMean([
      group({ group: "exposures", mean_percentile: 80, weight: 1.0 }),
      group({ group: "environmental_effects", mean_percentile: 20, weight: 0.5 }),
    ]);
    expect(mean).toBeCloseTo(60, 6);
  });

  it("gives two equally weighted groups their plain average", () => {
    const mean = weightedGroupMean([
      group({ group: "sensitive_populations", mean_percentile: 40, weight: 1.0 }),
      group({ group: "socioeconomic_factors", mean_percentile: 60, weight: 1.0 }),
    ]);
    expect(mean).toBe(50);
  });

  it("drops an uncomputable group rather than counting it as zero", () => {
    // Section 11 rule 1. Averaging a missing group in as zero would read as an
    // absence of burden, which is the failure the whole rule exists to prevent.
    const mean = weightedGroupMean([
      group({ mean_percentile: 80, weight: 1.0 }),
      group({
        group: "environmental_effects",
        mean_percentile: null,
        weight: 0.5,
        computable: false,
      }),
    ]);
    expect(mean).toBe(80);
    expect(mean).not.toBeCloseTo(53.33, 1);
  });

  it("returns nothing when no group is computable", () => {
    expect(weightedGroupMean([group({ computable: false, mean_percentile: null })])).toBeNull();
    expect(weightedGroupMean([])).toBeNull();
  });

  it("names the groups it left out", () => {
    const dropped = droppedGroups([
      group(),
      group({ group: "environmental_effects", computable: false, mean_percentile: null }),
    ]);
    expect(dropped).toHaveLength(1);
    expect(dropped[0].group).toBe("environmental_effects");
  });
});

describe("productOfComponents", () => {
  it("multiplies rather than averages the components", () => {
    const product = productOfComponents([
      { component: "pollution_burden", score: 9.5, groups: [] },
      { component: "population_characteristics", score: 2.0, groups: [] },
    ]);
    expect(product).toBeCloseTo(19, 6);
  });

  it("reproduces the worked consequence in section 10", () => {
    // A hex high on one axis scores below a hex middling on both. This is the
    // behaviour the panel explainer is there to prepare the reader for.
    const lopsided = productOfComponents([
      { component: "pollution_burden", score: 9.5, groups: [] },
      { component: "population_characteristics", score: 2.0, groups: [] },
    ]);
    const even = productOfComponents([
      { component: "pollution_burden", score: 6.0, groups: [] },
      { component: "population_characteristics", score: 6.0, groups: [] },
    ]);
    expect(even).toBeGreaterThan(lopsided as number);
  });

  it("returns nothing when there are no components", () => {
    expect(productOfComponents([])).toBeNull();
  });
});

describe("confidence", () => {
  it("carries section 12's weights, which sum to one", () => {
    const weights = confidenceTerms(confidence()).map((t) => t.weight);
    expect(weights).toEqual([0.35, 0.2, 0.25, 0.2]);
    expect(weights.reduce((a, b) => a + b, 0)).toBeCloseTo(1, 6);
  });

  it("names the term dragging the value down", () => {
    expect(weakestTerm(confidence()).id).toBe("monitor");
    expect(weakestTerm(confidence({ coverage: 0.1 })).id).toBe("coverage");
  });

  it("gives every band a plain-language reading", () => {
    for (const band of ["high", "moderate", "low", "insufficient"] as const) {
      expect(bandReading(band).length).toBeGreaterThan(20);
    }
  });

  it("leads with the caveat for the two bands section 12 hedges", () => {
    expect(leadsWithCaveat("low")).toBe(true);
    expect(leadsWithCaveat("insufficient")).toBe(true);
    expect(leadsWithCaveat("moderate")).toBe(false);
    expect(leadsWithCaveat("high")).toBe(false);
  });

  it("says an insufficient hex cannot produce a document", () => {
    // Section 12: generating a cited complaint from a score the system does not
    // trust is the most damaging thing this tool could do.
    expect(bandReading("insufficient")).toMatch(/cannot be used to generate a document/i);
  });
});

describe("isZeroInflated", () => {
  it("flags a facility indicator sitting at zero", () => {
    expect(isZeroInflated(indicator({ id: "F1", value: 0, percentile: 38 }))).toBe(true);
    expect(isZeroInflated(indicator({ id: "E3", value: 0, percentile: 38 }))).toBe(true);
  });

  it("leaves a facility indicator with an actual value alone", () => {
    expect(isZeroInflated(indicator({ id: "F1", value: 12.5 }))).toBe(false);
  });

  it("does not flag indicators the zero block does not apply to", () => {
    // Section 9 names E3 and F1 through F4 specifically. E1 is modelled and its
    // zero, if it ever occurred, would be an observation rather than an absence.
    expect(isZeroInflated(indicator({ id: "E1", value: 0 }))).toBe(false);
  });

  it("does not flag a missing indicator as a zero", () => {
    expect(isZeroInflated(indicator({ id: "F1", value: null, observed: false }))).toBe(false);
  });
});

describe("vintageFor", () => {
  it("finds an indicator's release through the source it names", () => {
    expect(vintageFor(indicator(), { "EPA AirToxScreen": "2021 release" })).toBe("2021 release");
  });

  it("reports nothing rather than guessing when CS-209 has not populated it", () => {
    expect(vintageFor(indicator(), {})).toBeNull();
  });
});
