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
  rendered: { properties: Record<string, unknown> }[] = [];
  flights: unknown[] = [];
  queried: unknown[] = [];
  fitted: unknown[] = [];

  constructor(public options: Record<string, unknown> = {}) {
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
  addSource() {}
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
  fitBounds(bounds: unknown) {
    this.fitted.push(bounds);
  }
  getContainer() {
    return document.createElement("div");
  }
}

vi.mock("maplibre-gl", () => ({
  Map: vi.fn(function (this: unknown, options: Record<string, unknown>) {
    return new FakeMap(options);
  }),
  NavigationControl: vi.fn(),
  ScaleControl: vi.fn(),
  addProtocol: vi.fn(),
  removeProtocol: vi.fn(),
  setWorkerUrl: vi.fn(),
}));

vi.mock("pmtiles", () => ({
  Protocol: vi.fn(function (this: { tile: unknown }) {
    this.tile = vi.fn();
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

describe("locked to Louisiana", () => {
  it("opens on the whole state and cannot leave it", async () => {
    const { LOUISIANA_BOUNDS, MAX_BOUNDS, MIN_ZOOM } = await import("../lib/louisiana.ts");
    const { map } = loadedMap();

    expect(map.options.bounds).toEqual(LOUISIANA_BOUNDS);
    expect(map.options.maxBounds).toEqual(MAX_BOUNDS);
    // The archive starts at zoom 6. Below it every hexagon disappears and the
    // reader is left looking at a map of the world.
    expect(map.options.minZoom).toBe(MIN_ZOOM);
    expect(MIN_ZOOM).toBeGreaterThanOrEqual(6);
    expect(map.options.renderWorldCopies).toBe(false);
  });

  it("offers a way back to the whole state", async () => {
    const { LOUISIANA_BOUNDS } = await import("../lib/louisiana.ts");
    const { map } = loadedMap();

    await userEvent.click(screen.getByRole("button", { name: "Show all of Louisiana" }));
    expect(map.fitted).toEqual([LOUISIANA_BOUNDS]);
  });
});
