import { afterEach, describe, expect, it, vi } from "vitest";

import { parseCoordinates, searchPlaces } from "./geocode.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("parseCoordinates", () => {
  it("reads latitude first, the way coordinates are written", () => {
    expect(parseCoordinates("30.05, -90.55")?.center).toEqual([-90.55, 30.05]);
  });

  it("accepts a space instead of a comma", () => {
    expect(parseCoordinates("30.05 -90.55")?.center).toEqual([-90.55, 30.05]);
  });

  it("recovers a reversed pair rather than sending the reader to the ocean", () => {
    // Only one of these can be a latitude, so the order is not ambiguous.
    expect(parseCoordinates("-90.55, 30.05")?.center).toEqual([-90.55, 30.05]);
  });

  it("rejects an out-of-range pair", () => {
    expect(parseCoordinates("200, 400")).toBeNull();
  });

  it("ignores anything that is not a coordinate pair", () => {
    expect(parseCoordinates("Baton Rouge")).toBeNull();
    expect(parseCoordinates("70805")).toBeNull();
  });

  it("does not call the network for a coordinate", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const places = await searchPlaces("30.05, -90.55");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(places).toHaveLength(1);
    expect(places[0].center).toEqual([-90.55, 30.05]);
  });
});

describe("searchPlaces", () => {
  function stubResponse(body: unknown, ok = true, status = 200) {
    const fetchMock = vi.fn().mockResolvedValue({
      ok,
      status,
      json: () => Promise.resolve(body),
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("returns nothing for a query too short to be meaningful", async () => {
    const fetchMock = stubResponse({ features: [] });
    expect(await searchPlaces("ba")).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps a Photon feature onto a place", async () => {
    stubResponse({
      features: [
        {
          geometry: { coordinates: [-91.187, 30.451] },
          properties: {
            name: "Baton Rouge",
            county: "East Baton Rouge Parish",
            state: "Louisiana",
            country: "United States",
            osm_type: "R",
            osm_id: 123,
          },
        },
      ],
    });

    const [place] = await searchPlaces("Baton Rouge");

    expect(place.name).toBe("Baton Rouge");
    expect(place.context).toBe("East Baton Rouge Parish, Louisiana, United States");
    expect(place.center).toEqual([-91.187, 30.451]);
  });

  it("biases the query toward the pilot state", async () => {
    const fetchMock = stubResponse({ features: [] });
    await searchPlaces("Springfield");

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.searchParams.get("lat")).toBe("30.6");
    expect(url.searchParams.get("lon")).toBe("-91.5");
    expect(url.searchParams.get("q")).toBe("Springfield");
  });

  it("drops a feature with no usable geometry instead of pinning it at null island", async () => {
    stubResponse({
      features: [
        { properties: { name: "Nowhere" } },
        { geometry: { coordinates: ["x", "y"] }, properties: { name: "Broken" } },
      ],
    });
    expect(await searchPlaces("nowhere")).toEqual([]);
  });

  it("survives a response that is not the shape we expect", async () => {
    stubResponse({ unexpected: true });
    expect(await searchPlaces("Baton Rouge")).toEqual([]);
  });

  it("reports an upstream failure rather than looking like no results", async () => {
    stubResponse(null, false, 503);
    await expect(searchPlaces("Baton Rouge")).rejects.toThrow("503");
  });
});
