/** Automated accessibility checks over every page (CS-401).
 *
 *  Axe catches the mechanical half: accessible names, roles, landmarks,
 *  heading order, form labels, link purpose. That half is the one that
 *  regresses silently, and this is what stops it.
 *
 *  **Two things it does not check here, so that nobody reads a green run as
 *  more than it is.** Colour contrast needs computed styles and jsdom has no
 *  layout engine, so axe reports that rule as incomplete rather than passing
 *  it — contrast is verified by hand against the ramp in docs/frontend.md and
 *  belongs in a real browser. And whether the low-confidence hatch stays
 *  distinguishable from the ramp itself is a judgement about a rendered map,
 *  which no DOM assertion reaches. CS-401's manual screen-reader pass is for
 *  exactly these.
 */

import { render } from "@testing-library/react";
import { axe } from "vitest-axe";
import * as matchers from "vitest-axe/matchers";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.tsx";
import { PAGES } from "./lib/pages.ts";

expect.extend(matchers);

vi.mock("./components/MapView.tsx", () => ({
  default: () => <div role="region" aria-label="Burden score map" />,
}));

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "",
        json: () =>
          Promise.resolve(
            new URL(url).pathname === "/provenance"
              ? { sources: [] }
              : { status: "ok", notes: [] },
          ),
      }),
    ),
  );
  vi.stubEnv("VITE_TILES_URL", "https://tiles.example/hexes.pmtiles");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("accessibility", () => {
  it.each(PAGES)("$label has no axe violations", async ({ path }) => {
    window.history.replaceState(null, "", path);
    const { container, findByRole } = render(<App />);
    await findByRole("heading", { level: 1 });

    expect(await axe(container)).toHaveNoViolations();
  });

  it("the not-found page has no axe violations", async () => {
    window.history.replaceState(null, "", "/nowhere");
    const { container, findByRole } = render(<App />);
    await findByRole("heading", { level: 1 });

    expect(await axe(container)).toHaveNoViolations();
  });
});
