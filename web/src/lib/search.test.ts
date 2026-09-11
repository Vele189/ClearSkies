import { describe, expect, it } from "vitest";

import { insidePilotState, parseQuery } from "./search.ts";

describe("parseQuery", () => {
  it("recognises an H3 index", () => {
    expect(parseQuery("88444600ddfffff")).toEqual({
      kind: "h3",
      h3: "88444600ddfffff",
    });
  });

  it("takes an index however it was pasted", () => {
    expect(parseQuery("  88444600DDFFFFF  ")).toEqual({
      kind: "h3",
      h3: "88444600ddfffff",
    });
  });

  it("reads a coordinate pair latitude first", () => {
    // The order a person reads off a map and the order consumer mapping tools
    // print. Getting it backwards would silently fly to the Indian Ocean.
    expect(parseQuery("30.45, -91.15")).toEqual({ kind: "coords", lat: 30.45, lon: -91.15 });
    expect(parseQuery("30.45 -91.15")).toEqual({ kind: "coords", lat: 30.45, lon: -91.15 });
  });

  it("rejects a coordinate that is out of range rather than searching for it", () => {
    // "91, -300" is a typo, not a town, and handing it to a geocoder wastes a
    // request to get nothing useful back.
    expect(parseQuery("91, -300")).toBeNull();
    expect(parseQuery("-95, 12")).toBeNull();
  });

  it("treats anything else as a place name", () => {
    expect(parseQuery("Reserve")).toEqual({ kind: "place", text: "Reserve" });
    expect(parseQuery("St. John the Baptist")).toEqual({
      kind: "place",
      text: "St. John the Baptist",
    });
  });

  it("returns nothing for an empty box", () => {
    expect(parseQuery("")).toBeNull();
    expect(parseQuery("   ")).toBeNull();
  });

  it("does not mistake a place with digits in it for a coordinate", () => {
    expect(parseQuery("Highway 61")).toEqual({ kind: "place", text: "Highway 61" });
  });
});

describe("insidePilotState", () => {
  it("knows Baton Rouge is in the scored state", () => {
    expect(insidePilotState(30.45, -91.15)).toBe(true);
  });

  it("knows Houston is not", () => {
    // Worth saying out loud rather than flying there silently: nothing outside
    // Louisiana is scored, so the map would look broken rather than empty.
    expect(insidePilotState(29.76, -95.37)).toBe(false);
  });
});
