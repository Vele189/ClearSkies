import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HexDetail } from "../lib/types.ts";
import HexPage from "./HexPage.tsx";

const H3 = "8844c0b18bfffff";

function detail(): HexDetail {
  return {
    h3: H3,
    resolution: 8,
    state: "LA",
    parish: "St. James",
    centroid: [-90.8, 30.0],
    score: 81.4,
    percentile: 94.2,
    components: [],
    indicators: [],
    confidence: {
      value: 0.71,
      band: "moderate",
      coverage: 0.8,
      recency: 0.9,
      spatial_support: 0.7,
      monitor_support: 0.4,
      nearest_monitor_km: 12.1,
    },
    demographics: { population: 1840 },
    facilities: [],
    facility_count: 0,
    no_score_reason: null,
    methodology_version: "0.2.0",
    data_vintage: {},
  };
}

function serve(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok,
        status: ok ? 200 : 404,
        statusText: "Not Found",
        json: () => Promise.resolve(body),
      }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the hexagon page", () => {
  it("renders one hexagon without a map", async () => {
    // CS-401's non-map path. The API already returns exactly what the panel
    // renders, so this is routing rather than a second implementation.
    serve(detail());

    render(<HexPage h3={H3} />);

    expect(await screen.findByText("St. James Parish")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /map/i })).not.toBeInTheDocument();
  });

  it("names the hexagon before the data arrives", async () => {
    serve(detail());

    render(<HexPage h3={H3} />);

    // The address is known immediately; a reader who followed a link should
    // see which hexagon they asked for rather than an empty page.
    expect(screen.getByText(H3)).toBeInTheDocument();
  });

  it("says so when the hexagon cannot be loaded, and offers the way back", async () => {
    serve({ detail: "no such hexagon" }, false);

    render(<HexPage h3={H3} />);

    expect(await screen.findByText("no such hexagon")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to the map/i })).toBeInTheDocument();
  });

  it("returns to the map when the panel is closed", async () => {
    serve(detail());
    render(<HexPage h3={H3} />);
    await screen.findByText("St. James Parish");

    await userEvent.click(screen.getByRole("button", { name: /close panel/i }));

    expect(window.location.pathname).toBe("/");
  });

  it("does not offer a link to the page it is already on", async () => {
    serve(detail());

    render(<HexPage h3={H3} />);
    await screen.findByText("St. James Parish");

    expect(screen.queryByRole("link", { name: /on its own page/i })).not.toBeInTheDocument();
  });
});
