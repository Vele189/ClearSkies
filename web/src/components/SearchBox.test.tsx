import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import SearchBox from "./SearchBox.tsx";

function stubPhoton(names: string[]) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () =>
      Promise.resolve({
        features: names.map((name, i) => ({
          geometry: { coordinates: [-91 - i, 30 + i] },
          properties: { name, state: "Louisiana", osm_type: "R", osm_id: 100 + i },
        })),
      }),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SearchBox", () => {
  it("exposes itself as a combobox to assistive technology", () => {
    render(<SearchBox onPick={vi.fn()} />);
    const input = screen.getByRole("combobox", { name: /search for a place/i });
    expect(input).toHaveAttribute("aria-expanded", "false");
  });

  it("offers matches for what was typed", async () => {
    stubPhoton(["Baton Rouge", "Baton Rouge Airport"]);
    render(<SearchBox onPick={vi.fn()} />);

    await userEvent.type(screen.getByRole("combobox"), "Baton Rouge");

    expect(await screen.findByRole("option", { name: /Baton Rouge Airport/ })).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "true");
  });

  it("is drivable from the keyboard alone", async () => {
    stubPhoton(["Baton Rouge", "Reserve"]);
    const onPick = vi.fn();
    render(<SearchBox onPick={onPick} />);

    const input = screen.getByRole("combobox");
    await userEvent.type(input, "Reserve");
    await screen.findByRole("option", { name: /Reserve/ });

    await userEvent.keyboard("{ArrowDown}{Enter}");

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick.mock.calls[0][0].name).toBe("Reserve");
  });

  it("dismisses the list on Escape without picking anything", async () => {
    stubPhoton(["Baton Rouge"]);
    const onPick = vi.fn();
    render(<SearchBox onPick={onPick} />);

    const input = screen.getByRole("combobox");
    await userEvent.type(input, "Baton Rouge");
    await screen.findByRole("option", { name: /Baton Rouge/ });

    await userEvent.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByRole("option")).not.toBeInTheDocument();
    });
    expect(onPick).not.toHaveBeenCalled();
  });

  it("debounces so a typed word is one request and not nine", async () => {
    const fetchMock = stubPhoton(["Reserve"]);
    render(<SearchBox onPick={vi.fn()} />);

    await userEvent.type(screen.getByRole("combobox"), "Reserve");
    await screen.findByRole("option", { name: /Reserve/ });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("says a search failed rather than showing an empty list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 503, json: () => Promise.resolve(null) }),
    );
    render(<SearchBox onPick={vi.fn()} />);

    await userEvent.type(screen.getByRole("combobox"), "Baton Rouge");

    expect(await screen.findByRole("status")).toHaveTextContent(/unavailable/i);
  });

  it("distinguishes no match from a broken search", async () => {
    stubPhoton([]);
    render(<SearchBox onPick={vi.fn()} />);

    await userEvent.type(screen.getByRole("combobox"), "Zzzzzz");

    expect(await screen.findByRole("status")).toHaveTextContent(/no match/i);
  });
});
