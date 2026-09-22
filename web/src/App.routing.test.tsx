import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.tsx";

vi.mock("./components/MapView.tsx", () => ({
  default: () => <div data-testid="map" />,
}));

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "",
        json: () => Promise.resolve({ status: "ok", notes: [] }),
      }),
    ),
  );
  vi.stubEnv("VITE_TILES_URL", "https://tiles.example/hexes.pmtiles");
});

describe("the shell", () => {
  it("renders the map at the root", async () => {
    render(<App />);

    expect(await screen.findByTestId("map")).toBeInTheDocument();
  });

  it("carries the disclaimer on every page", async () => {
    render(<App />);

    // CS-407 wants it on the app, and "on the app" has to mean every view: a
    // reader on a deep link passed through nowhere that could have said it.
    expect(
      screen.getByText(/not findings of wrongdoing by any facility or operator/i),
    ).toBeInTheDocument();
  });

  it("offers a skip link ahead of the navigation", async () => {
    render(<App />);
    const skip = screen.getByRole("link", { name: /skip to content/i });

    expect(skip).toHaveAttribute("href", "#main");
    // First in the tab order is the whole point of it.
    await userEvent.tab();
    expect(skip).toHaveFocus();
  });

  it("marks the current page for a screen reader, not only in colour", async () => {
    render(<App />);

    expect(screen.getByRole("link", { name: "Map" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("says so when nothing answers a path", async () => {
    window.history.replaceState(null, "", "/nowhere");

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: /nothing at this address/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("/nowhere")).toBeInTheDocument();
    expect(screen.queryByTestId("map")).not.toBeInTheDocument();
  });

  it("returns to the map from a dead end without a reload", async () => {
    window.history.replaceState(null, "", "/nowhere");
    render(<App />);

    await userEvent.click(screen.getByRole("link", { name: /back to the map/i }));

    expect(await screen.findByTestId("map")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
  });
});
