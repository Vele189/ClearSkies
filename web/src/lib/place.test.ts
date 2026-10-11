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

describe("where the state's name comes from", () => {
  it("prefers the name the API sent over the client's own table", () => {
    // `scored_state` holds the names now, so the client no longer has to keep
    // a list of FIPS codes in step with which states are scored. The local
    // table is a fallback for an older API and for the neighbouring codes a
    // hexagon on the state line can carry.
    expect(
      placeName({ parish: null, state: "54", state_name: "West Virginia" }),
    ).toBe("West Virginia");
  });

  it("falls back to the local table when the API did not say", () => {
    expect(placeName({ parish: null, state: "22", state_name: null })).toBe("Louisiana");
  });

  it("still refuses to print a FIPS code as a place", () => {
    expect(placeName({ parish: null, state: "99", state_name: null })).toBe(
      "Location not recorded",
    );
  });
});

