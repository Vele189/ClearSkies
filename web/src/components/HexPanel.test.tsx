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
    state_name: "Louisiana",
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
    facility_count: 0,
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

    expect(screen.getByText("no data here")).toBeInTheDocument();
    expect(screen.queryByText(/Bottom 0%/)).not.toBeInTheDocument();
  });

  it("counts dropped indicators so coverage gaps are visible", () => {
    render(
      <HexPanel
        hex={hex({ indicators: [indicator(), indicator({ id: "E4", observed: false, percentile: null })] })}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText(/No data for 1 of 2 measures/)).toBeInTheDocument();
  });

  it("explains an unscored hex instead of showing a blank score", () => {
    render(
      <HexPanel hex={hex({ score: null, percentile: null, no_score_reason: "low_population" })} onClose={() => {}} />,
    );

    expect(screen.getByText(/Not ranked: too few people live here/)).toBeInTheDocument();
    expect(screen.getByText(/Fewer than 25 people/)).toBeInTheDocument();
  });

  it("does not show an unscored hex as a poorly supported score", () => {
    // An unscored cell has no confidence to report. Showing four 0.00 terms, an
    // "insufficient data" badge and a caveat about "this score" described a
    // number that does not exist.
    render(
      <HexPanel
        hex={hex({
          score: null,
          percentile: null,
          no_score_reason: "low_population",
          confidence: { ...hex().confidence, band: "insufficient", value: 0 },
        })}
        onClose={() => {}}
      />,
    );
    expect(screen.queryByText("How complete the data is")).not.toBeInTheDocument();
    expect(screen.queryByText("Too little data")).not.toBeInTheDocument();
    expect(screen.queryByText(/too little data here to stand behind/i)).not.toBeInTheDocument();
  });

  it("states that the score is not a finding of wrongdoing", () => {
    // This disclaimer is a requirement, not decoration. It must not be
    // refactored away silently.
    render(<HexPanel hex={hex()} onClose={() => {}} />);

    expect(screen.getByText(/not a finding of wrongdoing/)).toBeInTheDocument();
  });
  it("shows each group's mean and the weight it carries", () => {
    render(<HexPanel hex={hex({ components: components() })} onClose={() => {}} />);

    expect(screen.getByText("Nearby industry")).toBeInTheDocument();
    // Section 10 weights Environmental Effects at half of Exposures. If that
    // ratio stops being visible the waterfall is not showing the composition.
    expect(screen.getByText("half weight")).toBeInTheDocument();
    expect(screen.getAllByText("full weight").length).toBeGreaterThan(0);
  });

  it("shows the weighted mean each component is built from", () => {
    // (1.0 * 80 + 0.5 * 20) / 1.5 = 60
    render(<HexPanel hex={hex({ components: components() })} onClose={() => {}} />);
    expect(screen.getByText("60.0 out of 100")).toBeInTheDocument();
  });

  it("admits that the rescale to 0-10 cannot be checked from the response", () => {
    render(<HexPanel hex={hex({ components: components() })} onClose={() => {}} />);
    expect(screen.getByText(/one step you can't check from this page/i)).toBeInTheDocument();
  });

  it("shows the components multiplying rather than adding", () => {
    render(<HexPanel hex={hex({ components: components() })} onClose={() => {}} />);
    expect(screen.getByText(/9\.5 × 2\.0 =/)).toBeInTheDocument();
    expect(screen.getByText(/multiply the two halves instead of adding them/i)).toBeInTheDocument();
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

    expect(screen.getByText(/not enough data, left out/i)).toBeInTheDocument();
    expect(screen.getByText(/rather than counted as zero/i)).toBeInTheDocument();
  });

  it("breaks confidence into its four terms with their weights", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);

    expect(screen.getByText("How complete the data is")).toBeInTheDocument();
    expect(screen.getByText("How recent the data is")).toBeInTheDocument();
    expect(screen.getByText("How well we know who lives here")).toBeInTheDocument();
    expect(screen.getByText("Distance to an air monitor")).toBeInTheDocument();
    expect(screen.getByText("counts 35%")).toBeInTheDocument();
  });

  it("explains why the terms are combined geometrically", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getByText(/one weak spot pulls the whole rating down/i)).toBeInTheDocument();
  });

  it("separates how sure we are from how bad it is", () => {
    // Section 12 forbids conflating the two, and the panel is where a reader is
    // most likely to do it.
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getByText(/not how bad the pollution is/i)).toBeInTheDocument();
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

    expect(screen.getAllByText(/treat this result as a rough guide/i).length).toBeGreaterThan(0);
  });

  it("does not lead with a caveat on a well-supported hex", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.queryByText(/treat this result as a rough guide/i)).not.toBeInTheDocument();
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

    expect(
      screen.getByText(/No plant with a major air pollution permit within 10 km/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Many places share this zero/i)).toBeInTheDocument();
  });

  it("says what a zero non-compliance burden means, not that nothing is nearby", () => {
    // F2 is zero where facilities are present and none was out of compliance.
    // "No qualifying facility" there contradicted the facility list beneath it.
    render(
      <HexPanel
        hex={hex({
          indicators: [
            indicator({ id: "F2", name: "Non-compliance burden", value: 0, percentile: 47 }),
          ],
        })}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/broke its permit rules in the last three years/i)).toBeInTheDocument();
    expect(screen.queryByText(/No qualifying/i)).not.toBeInTheDocument();
  });

  it("shows the measured value where its unit means something", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getByText("42 in a million")).toBeInTheDocument();
  });

  it("leads with the rank the map coloured, in words, then the score", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getAllByText("Top 4%").length).toBeGreaterThan(0);
    expect(screen.getByText(/most burdened in Louisiana/)).toBeInTheDocument();
    expect(screen.getByText("More burdened than 96% of places in Louisiana.")).toBeInTheDocument();
    expect(screen.getByText("78.4")).toBeInTheDocument();
  });

  it("never prints a top 0% or a 100th percentile", () => {
    render(<HexPanel hex={hex({ percentile: 99.97 })} onClose={() => {}} />);
    expect(screen.getAllByText("Top 1%").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Top 0%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/100th/)).not.toBeInTheDocument();
  });

  it("calls each measure by a plain name and says what it measures", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getByText("Cancer risk from toxic air")).toBeInTheDocument();
    expect(screen.getByText(/extra cancer cases/)).toBeInTheDocument();
  });

  it("lists each facility once, nearest first, and the rest on request", async () => {
    const facility = (id: string, km: number, program = "Clean Air Act") => ({
      registry_id: id,
      name: `Plant ${id}`,
      distance_km: km,
      program,
      echo_url: `https://echo.epa.gov/detailed-facility-report?fid=${id}`,
      quarters_in_noncompliance: 0,
      formal_actions_5yr: 0,
    });
    const facilities = [
      facility("1", 0.4),
      facility("1", 0.4, "RCRA large-quantity generator"),
      ...["2", "3", "4", "5", "6", "7"].map((id, i) => facility(id, 1 + i)),
    ];
    render(
      <HexPanel hex={hex({ facilities, facility_count: facilities.length })} onClose={() => {}} />,
    );

    expect(screen.getAllByRole("link", { name: /Plant 1/ })).toHaveLength(1);
    expect(screen.getByText(/Air permit, Hazardous waste producer/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Plant 7/ })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Show all 7 sites/ }));
    expect(screen.getByRole("link", { name: /Plant 7/ })).toBeInTheDocument();
  });

  it("takes focus when a hexagon is selected so the keyboard follows", () => {
    render(<HexPanel hex={hex()} onClose={() => {}} />);
    expect(screen.getByRole("complementary", { name: /Details for St. John the Baptist/ })).toHaveFocus();
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

  it("writes every rank as people say it", () => {
    render(
      <HexPanel
        hex={hex({
          percentile: 1,
          indicators: [indicator({ percentile: 22 })],
          components: [
            { component: "pollution_burden", score: 9.5, groups: [group({ mean_percentile: 11 })] },
          ],
        })}
        onClose={() => {}}
      />,
    );

    expect(screen.getAllByText("Bottom 1%").length).toBeGreaterThan(0);
    expect(screen.getByText("Bottom 22%")).toBeInTheDocument();
    // A group's average rank is not a rank, so it is not written as one.
    expect(screen.getByText("11/100")).toBeInTheDocument();
  });

  it("says a percentile is not reported rather than printing a bare suffix", () => {
    render(<HexPanel hex={hex({ percentile: null })} onClose={() => {}} />);

    expect(screen.getByText(/how it ranks in Louisiana wasn't reported/i)).toBeInTheDocument();
    expect(screen.queryByText(/^th percentile/)).not.toBeInTheDocument();
  });

  it("says no reason was recorded rather than trailing off after a colon", () => {
    render(<HexPanel hex={hex({ score: null, percentile: null, no_score_reason: null })} onClose={() => {}} />);

    expect(screen.getByText(/no reason was recorded/i)).toBeInTheDocument();
  });
});

// ---- Whose percentile this is -------------------------------------------

describe("the state a percentile belongs to", () => {
  it("names it from the hexagon rather than from the build", () => {
    // Section 9 ranks within a state and section 15 says the result does not
    // travel between them, so the panel has to say which state it ranked in.
    // It takes the name from the API because the API reads `scored_state`;
    // writing "Louisiana" in here would go stale on the first second state and
    // nothing would fail.
    const { container } = render(
      <HexPanel hex={hex({ state_name: "West Virginia" })} onClose={() => {}} />,
    );
    expect(container.textContent).toContain("Rankings compare places within West Virginia only.");
    expect(container.textContent).not.toContain("within Louisiana");
  });

  it("narrows the claim rather than guessing when the state is not given", () => {
    const { container } = render(
      <HexPanel hex={hex({ state_name: null })} onClose={() => {}} />,
    );
    expect(container.textContent).toContain("Rankings compare places within one state only.");
  });
});

