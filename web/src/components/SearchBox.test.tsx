import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SearchBox from "./SearchBox.tsx";

const getHex = vi.fn();

vi.mock("../lib/api.ts", () => ({
  getHex: (h3: string) => getHex(h3) as unknown,
  ApiError: class extends Error {},
}));

function search(text: string) {
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: text } });
  fireEvent.submit(screen.getByRole("search"));
}

beforeEach(() => {
  getHex.mockReset();
});

describe("the search box", () => {
  it("flies to a coordinate without asking anything of the network", () => {
    const onGoTo = vi.fn();
    render(<SearchBox onGoTo={onGoTo} onSelect={vi.fn()} />);

    search("30.45, -91.15");

    expect(onGoTo).toHaveBeenCalledWith(-91.15, 30.45, 12);
    expect(getHex).not.toHaveBeenCalled();
  });

  it("says so when a coordinate is outside the only state that is scored", () => {
    // It still flies there. The map would otherwise look broken rather than
    // empty, and a reader deserves to know which of the two they are seeing.
    const onGoTo = vi.fn();
    render(<SearchBox onGoTo={onGoTo} onSelect={vi.fn()} />);

    search("29.76, -95.37");

    expect(onGoTo).toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(/outside Louisiana/i);
  });

  it("resolves a hexagon index through the API and opens its panel", async () => {
    // Through the API rather than a client-side H3 library: one round trip
    // brings back both the centroid to fly to and the panel's content.
    const onGoTo = vi.fn();
    const onSelect = vi.fn();
    getHex.mockResolvedValue({ h3: "88444600ddfffff", centroid: [-90.555, 30.055] });
    render(<SearchBox onGoTo={onGoTo} onSelect={onSelect} />);

    search("88444600ddfffff");

    await waitFor(() => expect(onGoTo).toHaveBeenCalledWith(-90.555, 30.055, 13));
    expect(onSelect).toHaveBeenCalledWith("88444600ddfffff");
  });

  it("explains an index that does not resolve rather than clearing itself", async () => {
    // A search box that empties and does nothing is the least debuggable
    // control on a page.
    getHex.mockRejectedValue(new Error("404"));
    render(<SearchBox onGoTo={vi.fn()} onSelect={vi.fn()} />);

    search("88444600ddfffff");

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/No hexagon with that index/i),
    );
  });

  it("says place search is off rather than failing silently", () => {
    // VITE_GEOCODER_URL is unset in the test environment, which is also the
    // default: a deployment does not send what people type to a third party
    // unless somebody turned that on deliberately.
    render(<SearchBox onGoTo={vi.fn()} onSelect={vi.fn()} />);

    search("Reserve");

    expect(screen.getByRole("status")).toHaveTextContent(/Place search is off/i);
    expect(screen.getByRole("status")).toHaveTextContent(/H3 index, will still work/i);
  });

  it("asks for something usable when the box holds nonsense", () => {
    render(<SearchBox onGoTo={vi.fn()} onSelect={vi.fn()} />);

    search("   ");

    expect(screen.getByRole("status")).toHaveTextContent(/place, a latitude and longitude/i);
  });

  it("is reachable by keyboard and named for a screen reader", () => {
    render(<SearchBox onGoTo={vi.fn()} onSelect={vi.fn()} />);

    expect(
      screen.getByLabelText(/Search for a place, coordinate, or hexagon/i),
    ).toBeInTheDocument();
  });
});
