import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Provenance, SourcePull } from "../lib/types.ts";
import ProvenancePage from "./ProvenancePage.tsx";

function pull(over: Partial<SourcePull> = {}): SourcePull {
  return {
    source: "epa_echo",
    title: "EPA ECHO / ICIS",
    vintage: "2026-09-01",
    pulled_at: "2026-09-21T07:00:00Z",
    status: "ok",
    records: 12345,
    rejected: 0,
    run_id: "11",
    known_gaps: [],
    artifacts: [],
    notes: [],
    ...over,
  };
}

function serve(body: Provenance) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "",
        json: () => Promise.resolve(body),
      }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the provenance page", () => {
  it("renders from the live endpoint rather than a committed file", async () => {
    serve({ sources: [pull()] });

    render(<ProvenancePage />);

    expect(await screen.findByText("EPA ECHO / ICIS")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/provenance"),
      expect.anything(),
    );
  });

  it("shows the upstream release, not the download date", async () => {
    // A 2019 assessment pulled last night is 2019 data. Reporting the pull
    // date as the vintage would make the map look six years fresher than it is.
    serve({ sources: [pull({ vintage: "2019", title: "EPA AirToxScreen" })] });

    render(<ProvenancePage />);

    expect(await screen.findByText("Release")).toBeInTheDocument();
    expect(screen.getByText("2019")).toBeInTheDocument();
  });

  it("says when a source was served from a snapshot rather than fetched", async () => {
    // A `stale` run is exactly the situation a reader deserves to know about.
    serve({ sources: [pull({ status: "stale" })] });

    render(<ProvenancePage />);

    expect(await screen.findByText(/served from a snapshot/i)).toBeInTheDocument();
    expect(screen.getByText(/could not be reached/i)).toBeInTheDocument();
  });

  it("publishes a failed pull as a failed pull", async () => {
    // Not the most recent *successful* pull: a green row from three nights ago
    // would read as current.
    serve({ sources: [pull({ status: "failed", records: 0 })] });

    render(<ProvenancePage />);

    expect(await screen.findByText("Failed")).toBeInTheDocument();
  });

  it("lists what a source does not cover, and which indicators that degrades", async () => {
    serve({
      sources: [
        pull({
          known_gaps: [
            {
              scope: "temporal",
              detail: "The 2020 assessment publishes no tract-level file, so E1 and E2 are pinned to 2019.",
              affects: ["E1", "E2"],
              since: null,
            },
          ],
        }),
      ],
    });

    render(<ProvenancePage />);

    expect(await screen.findByText(/pinned to 2019/)).toBeInTheDocument();
    expect(screen.getByText(/Affects E1, E2/)).toBeInTheDocument();
  });

  it("explains the sparse sensors and the missing-value rule in plain language", async () => {
    serve({ sources: [pull()] });

    render(<ProvenancePage />);

    expect(await screen.findByText(/never shown as a zero/i)).toBeInTheDocument();
    expect(screen.getByText(/no report filed is an absence/i)).toBeInTheDocument();
    expect(screen.getByText(/monitors cover where the monitors are/i)).toBeInTheDocument();
  });

  it("does not let an empty table read as empty sources", async () => {
    serve({ sources: [] });

    render(<ProvenancePage />);

    expect(
      await screen.findByText(/means the pipeline has not run, not that the sources are empty/i),
    ).toBeInTheDocument();
  });

  it("says so when the endpoint cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));

    render(<ProvenancePage />);

    expect(await screen.findByText(/could not load the source records/i)).toBeInTheDocument();
  });
});
