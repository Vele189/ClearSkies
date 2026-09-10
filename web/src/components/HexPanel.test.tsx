import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HexDetail, IndicatorValue } from "../lib/types.ts";
import HexPanel from "./HexPanel.tsx";

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

function hex(over: Partial<HexDetail> = {}): HexDetail {
  return {
    h3: "88444600ddfffff",
    resolution: 8,
    state: "LA",
    parish: "St. John the Baptist",
    centroid: [-90.555, 30.055],
    score: 78.4,
    percentile: 96,
    components: [],
    indicators: [indicator()],
    confidence: {
      value: 0.82,
      band: "high",
      coverage: 0.9,
      recency: 0.8,
      spatial_support: 0.85,
      monitor_support: 0.7,
      nearest_monitor_km: 8.1,
    },
    demographics: { population: 1240 },
    facilities: [],
    no_score_reason: null,
    methodology_version: "0.1.1",
    data_vintage: {},
    ...over,
  };
}

describe("HexPanel", () => {
  it("shows an unobserved indicator as not observed, never as zero", () => {
    // Methodology section 11: a missing indicator is dropped, never imputed.
    // Rendering it as 0 would read as 'clean' and invert the meaning.
    render(<HexPanel hex={hex({ indicators: [indicator({ observed: false, percentile: null })] })} onClose={() => {}} />);

    expect(screen.getByText("not observed")).toBeInTheDocument();
    expect(screen.queryByText("0th")).not.toBeInTheDocument();
  });

  it("counts dropped indicators so coverage gaps are visible", () => {
    render(
      <HexPanel
        hex={hex({ indicators: [indicator(), indicator({ id: "E4", observed: false, percentile: null })] })}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText(/1 of 2 indicators unavailable/)).toBeInTheDocument();
  });

  it("explains an unscored hex instead of showing a blank score", () => {
    render(
      <HexPanel hex={hex({ score: null, percentile: null, no_score_reason: "low_population" })} onClose={() => {}} />,
    );

    expect(screen.getByText(/Not scored: low population/)).toBeInTheDocument();
  });

  it("states that the score is not a finding of wrongdoing", () => {
    // This disclaimer is a requirement, not decoration. It must not be
    // refactored away silently.
    render(<HexPanel hex={hex()} onClose={() => {}} />);

    expect(screen.getByText(/not a finding of wrongdoing/)).toBeInTheDocument();
  });
});
