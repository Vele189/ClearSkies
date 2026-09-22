import { describe, expect, it } from "vitest";

import { placeName, stateName } from "./place.ts";

describe("placeName", () => {
  it("prefers the parish, which is the most specific name there is", () => {
    expect(placeName({ parish: "East Baton Rouge", state: "22" })).toBe(
      "East Baton Rouge Parish",
    );
  });

  it("never renders a FIPS code as a place", () => {
    // The bug this exists for: not one of the 173,424 loaded hexagons carries
    // a parish name, so every panel heading read "22".
    expect(placeName({ parish: null, state: "22" })).toBe("Louisiana");
    expect(placeName({ parish: null, state: "22" })).not.toBe("22");
  });

  it("says the location is unrecorded rather than printing an unknown code", () => {
    const heading = placeName({ parish: null, state: "99" });

    expect(heading).toBe("Location not recorded");
    expect(heading).not.toContain("99");
  });

  it("knows the pilot state and the ones a line hexagon can reach", () => {
    expect(stateName("22")).toBe("Louisiana");
    expect(stateName("48")).toBe("Texas");
    expect(stateName("99")).toBeNull();
  });
});
