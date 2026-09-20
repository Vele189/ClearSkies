import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ComponentScore, GroupScore, HexDetail, IndicatorValue } from "../lib/types.ts";
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

/** The two components as methodology section 10 composes them, so a test can
 *  assert the panel narrates the real arithmetic and not a simplified one. */
function components(): ComponentScore[] {
  return [
    {
      component: "pollution_burden",
      score: 9.5,
      groups: [
        group({ group: "exposures", mean_percentile: 80, weight: 1.0 }),
        group({ group: "environmental_effects", mean_percentile: 20, weight: 0.5 }),
      ],
    },
    {
      component: "population_characteristics",
      score: 2.0,
      groups: [
        group({ group: "sensitive_populations", mean_percentile: 40, weight: 1.0 }),
        group({ group: "socioeconomic_factors", mean_percentile: 60, weight: 1.0 }),
      ],
    },
  ];
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
  it("shows each group's mean and the weight it carries", () => {
    render(<HexPanel hex={hex({ components: components() })} onClose={() => {}} />);

    expect(screen.getByText("Environmental effects")).toBeInTheDocument();
    // Section 10 weights Environmental Effects at half of Exposures. If that
    // ratio stops being visible the waterfall is not showing the composition.
    expect(screen.getByText("×0.5")).toBeInTheDocument();
    expect(screen.getAllByText("×1.0").length).toBeGreaterThan(0);
  });

  it("shows the weighted mean each component is built from", () => {
    // (1.0 * 80 + 0.5 * 20) / 1.5 = 60
    render(<HexPanel hex={hex({ components: components() })} onClose={() => {}} />);
    expect(screen.getByText(/60.0th percentile/)).toBeInTheDocument();
  });

  it("admits that the rescale to 0-10 cannot be checked from the response", () => {
    render(<HexPanel hex={hex({ components: components() })} onClose={() => {}} />);
    expect(screen.getByText(/cannot be checked here/i)).toBeInTheDocument();
  });

  it("shows the components multiplying rather than adding", () => {
    render(<HexPanel hex={hex({ components: components() })} onClose={() => {}} />);
    expect(screen.getByText(/9\.5 × 2\.0 =/)).toBeInTheDocument();
    expect(screen.getByText(/compound rather than offset/i)).toBeInTheDocument();
  });

  it("names a dropped group rather than leaving the weights unexplained", () => {
    const withGap = components();
    withGap[0].groups[1] = group({
      group: "environmental_effects",
      mean_percentile: null,
      weight: 0.5,
      computable: false,
    });

    render(<HexPanel hex={hex({ components: withGap })} onClose={() => {}} />);

    expect(screen.getByText(/not computable, dropped/i)).toBeInTheDocument();
    expect(screen.getByText(/rather than counted as zero/i)).toBeInTheDocument();
  });

  it("breaks confidence into its four terms with their weights", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);

    expect(screen.getByText("Indicator coverage")).toBeInTheDocument();
    expect(screen.getByText("Recency")).toBeInTheDocument();
    expect(screen.getByText("Spatial support")).toBeInTheDocument();
    expect(screen.getByText("Monitor support")).toBeInTheDocument();
    expect(screen.getByText("×0.35")).toBeInTheDocument();
  });

  it("explains why the terms are combined geometrically", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getByText(/not smoothed away by three healthy ones/i)).toBeInTheDocument();
  });

  it("separates how sure we are from how bad it is", () => {
    // Section 12 forbids conflating the two, and the panel is where a reader is
    // most likely to do it.
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getByText(/never how severe the burden is/i)).toBeInTheDocument();
  });

  it("leads with the caveat on a low-confidence hex", () => {
    const low = hex({
      confidence: {
        value: 0.45,
        band: "low",
        coverage: 0.5,
        recency: 0.6,
        spatial_support: 0.4,
        monitor_support: 0.3,
        nearest_monitor_km: 84,
      },
    });
    render(<HexPanel hex={low} onClose={() => {}} />);

    expect(screen.getAllByText(/treat this score as indicative/i).length).toBeGreaterThan(0);
  });

  it("does not lead with a caveat on a well-supported hex", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.queryByText(/treat this score as indicative/i)).not.toBeInTheDocument();
  });

  it("names the source of every indicator", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getByText(/EPA AirToxScreen/)).toBeInTheDocument();
  });

  it("shows a vintage once CS-209 populates one, and nothing before then", () => {
    const { unmount } = render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.queryByText(/2021 release/)).not.toBeInTheDocument();
    unmount();

    render(
      <HexPanel
        hex={hex({ data_vintage: { "EPA AirToxScreen": "2021 release" } })}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/2021 release/)).toBeInTheDocument();
  });

  it("warns that a zero facility indicator is not a ranking", () => {
    // Methodology section 9 requires this limitation on the panel rather than
    // smoothed over: it means 'none within 10 km', not 'cleaner than 40%'.
    render(
      <HexPanel
        hex={hex({
          indicators: [
            indicator({ id: "F1", name: "Major source proximity", value: 0, percentile: 38 }),
          ],
        })}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText(/No qualifying facility within 10 km/i)).toBeInTheDocument();
  });

  it("takes focus when a hexagon is selected so the keyboard follows", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getByRole("complementary", { name: /Details for hexagon/ })).toHaveFocus();
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<HexPanel hex={hex()} onClose={onClose} />);

    await userEvent.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("reaches the close button and every facility link by keyboard", async () => {
    render(
      <HexPanel
        hex={hex({
          facilities: [
            {
              registry_id: "110000123456",
              name: "Example Chemical Works",
              distance_km: 1.2,
              program: "CAA",
              echo_url: "https://echo.epa.gov/detailed-facility-report?fid=110000123456",
              quarters_in_noncompliance: 3,
              formal_actions_5yr: 1,
            },
          ],
        })}
        onClose={() => {}}
      />,
    );

    await userEvent.tab();
    expect(screen.getByRole("button", { name: /close panel/i })).toHaveFocus();

    await userEvent.tab();
    expect(screen.getByRole("link", { name: /Example Chemical Works/ })).toHaveFocus();
  });
});
