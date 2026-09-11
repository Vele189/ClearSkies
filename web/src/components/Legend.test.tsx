import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Legend from "./Legend.tsx";

describe("the legend", () => {
  it("says the percentiles are Louisiana percentiles", () => {
    // The most common way a score like this gets misread, per section 15, so
    // the caveat is on the map rather than only in the documentation.
    render(<Legend showUntrusted={false} onToggleUntrusted={vi.fn()} />);

    expect(screen.getByText(/Louisiana 90th is not a national 90th/i)).toBeInTheDocument();
  });

  it("marks the top decile the validation protocol gates on", () => {
    render(<Legend showUntrusted={false} onToggleUntrusted={vi.fn()} />);

    expect(screen.getByText("90")).toBeInTheDocument();
    expect(screen.getByText(/top decile/i)).toBeInTheDocument();
  });

  it("explains all three confidence treatments the map draws", () => {
    // A reader who cannot tell a hatched hex from a solid one is reading a map
    // that is quietly lying about how much it knows.
    render(<Legend showUntrusted={false} onToggleUntrusted={vi.fn()} />);

    expect(screen.getByText(/High or moderate, drawn plainly/i)).toBeInTheDocument();
    expect(screen.getByText(/Low, hatched/i)).toBeInTheDocument();
    expect(screen.getByText(/Not scored; the panel says why/i)).toBeInTheDocument();
  });

  it("keeps the untrusted hexes off by default and offers the toggle", () => {
    render(<Legend showUntrusted={false} onToggleUntrusted={vi.fn()} />);

    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByText(/cannot produce a document/i)).toBeInTheDocument();
  });

  it("asks for the untrusted hexes when the toggle is used", () => {
    const onToggle = vi.fn();
    render(<Legend showUntrusted={false} onToggleUntrusted={onToggle} />);

    fireEvent.click(screen.getByRole("checkbox"));

    expect(onToggle).toHaveBeenCalledWith(true);
  });

  it("does not let confidence be read as severity", () => {
    // Section 12 is explicit that the interface must never conflate the two.
    render(<Legend showUntrusted={false} onToggleUntrusted={vi.fn()} />);

    expect(
      screen.getByText(/how well supported a score is, never how severe/i),
    ).toBeInTheDocument();
  });
});
