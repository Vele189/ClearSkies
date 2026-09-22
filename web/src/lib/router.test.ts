import { beforeEach, describe, expect, it, vi } from "vitest";

import { match, navigate, NAVIGATION_EVENT } from "./router.ts";

describe("match", () => {
  it("matches an exact path", () => {
    expect(match("/provenance", "/provenance")).toEqual({});
  });

  it("does not prefix-match, so / is not every path", () => {
    expect(match("/", "/provenance")).toBeNull();
    expect(match("/provenance", "/provenance/extra")).toBeNull();
  });

  it("fills a named parameter", () => {
    expect(match("/hex/:h3", "/hex/8844c0b18bfffff")).toEqual({ h3: "8844c0b18bfffff" });
  });

  it("refuses an empty parameter rather than matching with nothing in it", () => {
    // `/hex/` matching would send the API a request for no hexagon at all.
    expect(match("/hex/:h3", "/hex/")).toBeNull();
  });

  it("decodes a parameter", () => {
    expect(match("/x/:v", "/x/a%20b")).toEqual({ v: "a b" });
  });

  it("ignores a trailing slash", () => {
    expect(match("/provenance", "/provenance/")).toEqual({});
  });
});

describe("navigate", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("changes the path without a reload and tells subscribers", () => {
    const listener = vi.fn();
    window.addEventListener(NAVIGATION_EVENT, listener);

    navigate("/provenance");

    expect(window.location.pathname).toBe("/provenance");
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(NAVIGATION_EVENT, listener);
  });

  it("does not push a history entry for the path already showing", () => {
    // Otherwise clicking the current nav item fills the back button with
    // copies of the page the reader is already on.
    const listener = vi.fn();
    navigate("/provenance");
    window.addEventListener(NAVIGATION_EVENT, listener);

    navigate("/provenance");

    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(NAVIGATION_EVENT, listener);
  });
});
