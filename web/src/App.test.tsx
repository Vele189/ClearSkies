import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.tsx";
import type { DraftResponse, HexDetail } from "./lib/types.ts";

// The real map needs WebGL. What App owns is what happens after a hexagon is
// selected, so the map is replaced by one button per hexagon that selects it.
vi.mock("./components/MapView.tsx", () => ({
  default: ({ onSelect }: { onSelect: (h3: string) => void }) => (
    <div>
      <button onClick={() => onSelect(A)}>select A</button>
      <button onClick={() => onSelect(B)}>select B</button>
    </div>
  ),
}));

const A = "88444600ddfffff";
const B = "88444600dbfffff";

function detail(h3: string, parish: string): HexDetail {
  return {
    h3,
    resolution: 8,
    state: "LA",
    parish,
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
    methodology_version: "0.1.4",
    data_vintage: {},
  };
}

const DRAFTED: DraftResponse = {
  status: "drafted",
  from_cache: false,
  refusal: null,
  draft: {
    document: {
      document_type: "public_comment_letter",
      draft_notice: "DRAFT FOR HUMAN REVIEW. It is not legal advice.",
      citations: [],
      paragraphs: [{ text: "A paragraph about St. James.", citations: [] }],
      recipient: "LDEQ",
      subject: "Comment",
    },
    h3: A,
    confidence_band: "moderate",
    methodology_version: "0.1.4",
    corpus_version: "appendix-b-test",
    prompt_version: "v1",
    model: "gpt-4o",
    generated_at: "2026-09-11T16:04:59Z",
    review_required: true,
  },
};

function ok(body: unknown) {
  return { ok: true, status: 200, statusText: "", json: () => Promise.resolve(body) };
}

/** Responses the test releases by hand, keyed by path, so it controls the
 *  order they land in. Anything not held answers at once. */
function routedFetch(held: string[] = []) {
  const releases = new Map<string, () => void>();
  const signals = new Map<string, AbortSignal | undefined>();
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const path = new URL(url).pathname;
    signals.set(path, init?.signal ?? undefined);
    const body =
      path === "/health"
        ? { status: "ok", notes: [] }
        : path === `/hex/${A}`
          ? detail(A, "St. James")
          : path === `/hex/${B}`
            ? detail(B, "Iberville")
            : DRAFTED;
    if (!held.includes(path)) return Promise.resolve(ok(body));
    return new Promise((resolve) => releases.set(path, () => resolve(ok(body))));
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    release: (path: string) => releases.get(path)?.(),
    signal: (path: string) => signals.get(path),
  };
}

beforeEach(() => {
  vi.stubEnv("VITE_TILES_URL", "https://tiles.example/hexes.pmtiles");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("selecting a hexagon", () => {
  it("clears the last hexagon's draft when another is selected", async () => {
    routedFetch();
    render(<App />);

    await userEvent.click(screen.getByText("select A"));
    await screen.findByText("St. James Parish");
    await userEvent.click(screen.getByText("Public comment letter"));
    expect(await screen.findByText("A paragraph about St. James.")).toBeInTheDocument();

    await userEvent.click(screen.getByText("select B"));
    await screen.findByText("Iberville Parish");

    expect(screen.queryByText("A paragraph about St. James.")).not.toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("abandons a draft in flight when another hexagon is selected", async () => {
    const { release, signal } = routedFetch(["/draft"]);
    render(<App />);

    await userEvent.click(screen.getByText("select A"));
    await screen.findByText("St. James Parish");
    await userEvent.click(screen.getByText("Public comment letter"));
    await waitFor(() => expect(signal("/draft")).toBeDefined());

    await userEvent.click(screen.getByText("select B"));
    await screen.findByText("Iberville Parish");
    expect(signal("/draft")?.aborted).toBe(true);

    await act(async () => {
      release("/draft");
      await Promise.resolve();
    });
    expect(screen.queryByText("A paragraph about St. James.")).not.toBeInTheDocument();
  });

  it("shows the hexagon clicked last even when an earlier one answers later", async () => {
    const { release, signal } = routedFetch([`/hex/${A}`]);
    render(<App />);

    await userEvent.click(screen.getByText("select A"));
    expect(await screen.findByRole("status")).toHaveTextContent(/loading hexagon/i);

    await userEvent.click(screen.getByText("select B"));
    await screen.findByText("Iberville Parish");
    expect(signal(`/hex/${A}`)?.aborted).toBe(true);

    await act(async () => {
      release(`/hex/${A}`);
      await Promise.resolve();
    });
    expect(screen.getByText("Iberville Parish")).toBeInTheDocument();
    expect(screen.queryByText("St. James Parish")).not.toBeInTheDocument();
  });

  it("says a hexagon is loading rather than showing the previous one", async () => {
    const { release } = routedFetch([`/hex/${B}`]);
    render(<App />);

    await userEvent.click(screen.getByText("select A"));
    await screen.findByText("St. James Parish");

    await userEvent.click(screen.getByText("select B"));
    expect(screen.queryByText("St. James Parish")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(B);

    await act(async () => {
      release(`/hex/${B}`);
      await Promise.resolve();
    });
    expect(await screen.findByText("Iberville Parish")).toBeInTheDocument();
  });
});
