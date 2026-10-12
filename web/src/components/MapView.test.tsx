import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MapView from "./MapView.tsx";

type Listener = (event?: unknown) => void;

/** Just enough of a MapLibre map to drive MapView without WebGL: events can be
 *  fired by hand, and what is "rendered" at a point is whatever the test says. */
class FakeMap {
  static last: FakeMap | null = null;

  listeners = new Map<string, { fn: Listener; layer?: string; once: boolean }[]>();
  layers = new Set<string>();
  tilesLoaded = true;
  fits: { bounds: unknown; options: unknown }[] = [];
  sources = new Map<string, { data: unknown }>();
  container: HTMLElement | null = document.createElement("div");
  rendered: { properties: Record<string, unknown> }[] = [];
  flights: unknown[] = [];
  queried: unknown[] = [];

  constructor() {
    FakeMap.last = this;
  }

  private add(type: string, fn: Listener, layer: string | undefined, once: boolean) {
    const list = this.listeners.get(type) ?? [];
    list.push({ fn, layer, once });
    this.listeners.set(type, list);
  }

  on(type: string, layerOrFn: string | Listener, fn?: Listener) {
    if (typeof layerOrFn === "string") this.add(type, fn as Listener, layerOrFn, false);
    else this.add(type, layerOrFn, undefined, false);
    return this;
  }

  once(type: string, fn: Listener) {
    this.add(type, fn, undefined, true);
    return this;
  }

  off(type: string, fn: Listener) {
    this.listeners.set(
      type,
      (this.listeners.get(type) ?? []).filter((l) => l.fn !== fn),
    );
    return this;
  }

  fire(type: string, event?: unknown, layer?: string) {
    const list = this.listeners.get(type) ?? [];
    this.listeners.set(
      type,
      list.filter((l) => !l.once),
    );
    for (const l of list) if (l.layer === layer) l.fn(event);
  }

  addControl() {}
  getCanvas() {
    return document.createElement("canvas");
  }
  hasImage() {
    return false;
  }
  addImage() {}
  addSource(id: string) {
    this.sources.set(id, { data: null as unknown });
  }
  getSource(id: string) {
    const held = this.sources.get(id);
    if (!held) return undefined;
    return {
      setData: (data: unknown) => {
        held.data = data;
      },
    };
  }
  addLayer(layer: { id: string }) {
    this.layers.add(layer.id);
  }
  getLayer(id: string) {
    return this.layers.has(id) ? { id } : undefined;
  }
  setFilter() {}
  remove() {}
  stop() {}
  areTilesLoaded() {
    return this.tilesLoaded;
  }
  project(center: [number, number]) {
    return { x: center[0], y: center[1] };
  }
  queryRenderedFeatures(point: unknown, options: unknown) {
    this.queried.push({ point, options });
    return this.rendered;
  }
  flyTo(options: unknown) {
    this.flights.push(options);
  }
  fitBounds(bounds: unknown, options: unknown) {
    this.fits.push({ bounds, options });
  }
  getContainer() {
    return this.container;
  }
}

vi.mock("maplibre-gl", () => ({
  Map: vi.fn(function (this: unknown) {
    return new FakeMap();
  }),
  NavigationControl: vi.fn(),
  ScaleControl: vi.fn(),
  addProtocol: vi.fn(),
  removeProtocol: vi.fn(),
}));

//: Louisiana's bounds, as the real archive's header carries them.
const ARCHIVE_BOUNDS = { minLon: -94.14, minLat: 28.83, maxLon: -88.73, maxLat: 33.1 };

vi.mock("pmtiles", () => ({
  Protocol: vi.fn(function (this: { tile: unknown; add: unknown }) {
    this.tile = vi.fn();
    this.add = vi.fn();
  }),
  PMTiles: vi.fn(function (this: { getHeader: unknown }) {
    this.getHeader = vi.fn(() => Promise.resolve(ARCHIVE_BOUNDS));
  }),
}));

function stubPhoton(name: string, center: [number, number]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          features: [
            {
              geometry: { coordinates: center },
              properties: { name, state: "Louisiana", osm_type: "R", osm_id: 1 },
            },
          ],
        }),
    }),
  );
}

function loadedMap(onSelect = vi.fn()) {
  render(<MapView onSelect={onSelect} />);
  const map = FakeMap.last as FakeMap;
  act(() => map.fire("load"));
  return { map, onSelect };
}

async function pick(name: string) {
  await userEvent.type(screen.getByRole("combobox"), name);
  await screen.findByRole("option", { name: new RegExp(name) });
  await userEvent.keyboard("{Enter}");
}

const STATES = [
  {
    usps: "LA",
    name: "Louisiana",
    centroid: [-91.4, 30.94],
    bounds: [-94.04, 28.86, -88.76, 33.02],
    cells: 171725,
  },
  {
    usps: "DC",
    name: "District of Columbia",
    centroid: [-77.02, 38.89],
    bounds: [-77.12, 38.8, -76.92, 38.99],
    cells: 246,
  },
];

function stubStates() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(STATES) }),
  );
}

beforeEach(() => {
  vi.stubEnv("VITE_TILES_URL", "https://tiles.example/hexes.pmtiles");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  FakeMap.last = null;
});

describe("MapView", () => {
  it("is a named region a screen reader can land on", () => {
    loadedMap();
    expect(screen.getByRole("region", { name: "Burden score map" })).toBeInTheDocument();
  });

  it("frames what is scored rather than the state it started as", async () => {
    // The camera used to open on two constants holding Louisiana, with a
    // comment saying a later phase would fit them to the scored extent. Once a
    // second state was loaded the map opened over the pilot state and a reader
    // could not see that anywhere else had been scored at all.
    //
    // The bounds come from the archive's own header, which is metadata rather
    // than data: exact, free of tile reads, and right the first time a state is
    // added without anybody editing a number here.
    const { map } = loadedMap();
    await vi.waitFor(() => expect(map.fits).toHaveLength(1));

    expect(map.fits[0].bounds).toEqual([
      [ARCHIVE_BOUNDS.minLon, ARCHIVE_BOUNDS.minLat],
      [ARCHIVE_BOUNDS.maxLon, ARCHIVE_BOUNDS.maxLat],
    ]);
  });

  it("marks where each scored state is, for the zooms that have no hexes", async () => {
    // Below zoom 6 the archive has no tiles at all, so a reader who zooms out
    // to find the other states is looking at an empty basemap with nothing to
    // say anywhere else was scored. The rings are what they aim at.
    stubStates();
    const { map } = loadedMap();

    expect(map.layers.has("clearskies-state-circle")).toBe(true);
    expect(map.layers.has("clearskies-state-label")).toBe(true);

    await vi.waitFor(() => {
      const held = map.sources.get("clearskies-states");
      expect((held?.data as { features: unknown[] } | null)?.features).toHaveLength(2);
    });

    const data = map.sources.get("clearskies-states")?.data as {
      features: { geometry: { coordinates: number[] }; properties: Record<string, unknown> }[];
    };
    const dc = data.features.find((f) => f.properties.usps === "DC");

    expect(dc?.geometry.coordinates).toEqual([-77.02, 38.89]);
    expect(dc?.properties.cells).toBe(246);
    // Four numbers rather than one array: a GeoJSON property holding an array
    // does not survive a feature round trip the same way on every path.
    expect(dc?.properties.west).toBe(-77.12);
    expect(dc?.properties.north).toBe(38.99);
  });

  it("selects the hexagon a reader clicks", () => {
    const { map, onSelect } = loadedMap();
    map.fire("click", { features: [{ properties: { h3: "88444600ddfffff" } }] }, "clearskies-hex-fill");
    expect(onSelect).toHaveBeenCalledWith("88444600ddfffff");
  });

  it("selects the hexagon under a search pick once the flight settles", async () => {
    // Clicking is otherwise the only way into a panel, which leaves a keyboard
    // reader shown the right place with no way to open it.
    stubPhoton("Reserve", [-90.55, 30.05]);
    const { map, onSelect } = loadedMap();
    map.rendered = [{ properties: { h3: "88444600ddfffff" } }];

    await pick("Reserve");
    expect(map.flights).toHaveLength(1);
    expect(onSelect).not.toHaveBeenCalled();

    act(() => map.fire("moveend"));
    expect(onSelect).toHaveBeenCalledWith("88444600ddfffff");
    expect(map.queried[0]).toEqual({
      point: { x: -90.55, y: 30.05 },
      options: { layers: ["clearskies-hex-fill"] },
    });
  });

  it("waits for the tiles at the destination before selecting", async () => {
    stubPhoton("Reserve", [-90.55, 30.05]);
    const { map, onSelect } = loadedMap();
    map.rendered = [{ properties: { h3: "88444600ddfffff" } }];
    map.tilesLoaded = false;

    await pick("Reserve");
    act(() => map.fire("moveend"));
    expect(onSelect).not.toHaveBeenCalled();

    act(() => map.fire("idle"));
    expect(onSelect).toHaveBeenCalledWith("88444600ddfffff");
  });

  it("selects nothing where no hexagon is drawn", async () => {
    stubPhoton("Reserve", [-90.55, 30.05]);
    const { map, onSelect } = loadedMap();

    await pick("Reserve");
    act(() => map.fire("moveend"));
    expect(onSelect).not.toHaveBeenCalled();
  });
});
