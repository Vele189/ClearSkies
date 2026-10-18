/** What the masthead claims this deployment covers.
 *
 *  Coverage moved out of the API's configuration and into `scored_state` in
 *  migration 0031, because a single-valued PILOT_STATE cannot express two
 *  states and because a deploy whose environment disagreed with its database
 *  would be wrong in the one direction nobody checks. This is the line a
 *  reader sees on every page, so it is the place that wrongness would be most
 *  read and least noticed.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.tsx";
import type { ScoredState } from "./lib/types.ts";

vi.mock("./components/MapView.tsx", () => ({
  default: () => <div role="region" aria-label="Burden score map" />,
}));

function healthWith(scored_states: ScoredState[] | undefined) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "",
        json: () =>
          Promise.resolve(
            new URL(url).pathname === "/health"
              ? { status: "ok", notes: [], ...(scored_states ? { scored_states } : {}) }
              : { sources: [] },
          ),
      }),
    ),
  );
}

const LA = { usps: "LA", name: "Louisiana" };
const WV = { usps: "WV", name: "West Virginia" };
const DE = { usps: "DE", name: "Delaware" };

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.stubEnv("VITE_TILES_URL", "https://tiles.example/hexes.pmtiles");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

async function masthead(): Promise<string> {
  const { container } = render(<App />);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  await screen.findByRole("heading", { level: 1 });
  return container.textContent ?? "";
}

describe("the masthead's coverage line", () => {
  it("names the one state that is scored", async () => {
    healthWith([LA]);
    expect(await masthead()).toContain("How much pollution communities live with in Louisiana");
  });

  it("names both when two are scored", async () => {
    healthWith([LA, WV]);
    expect(await masthead()).toContain(
      "How much pollution communities live with in Louisiana and West Virginia",
    );
  });

  it("counts them past two rather than listing them into the masthead", async () => {
    healthWith([LA, WV, DE]);
    expect(await masthead()).toContain("How much pollution communities live with across 3 states");
  });

  it("names no state at all when coverage is unknown", async () => {
    // An empty or absent list means the database could not be reached, which
    // is a different thing from nothing being scored. Naming a state on the
    // strength of a default would be guessing about the one fact this line
    // exists to carry.
    healthWith(undefined);
    const text = await masthead();
    expect(text).toContain("How much pollution communities live with");
    expect(text).not.toContain("live with in Louisiana");
  });
});
