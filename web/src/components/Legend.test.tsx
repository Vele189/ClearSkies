import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LEGEND_CLASSES } from "../lib/ramp.ts";
import Legend from "./Legend.tsx";

function renderLegend(showInsufficient = false) {
  const onChange = vi.fn();
  render(
    <Legend showInsufficient={showInsufficient} onShowInsufficientChange={onChange} />,
  );
  return onChange;
}

describe("Legend", () => {
  it("is present without the reader having to open anything", () => {
    renderLegend();
    expect(screen.getByRole("region", { name: /map legend/i })).toBeInTheDocument();
  });

  it("labels every class on the ramp", () => {
    renderLegend();
    for (const cls of LEGEND_CLASSES) {
      expect(screen.getByText(cls.label)).toBeInTheDocument();
    }
  });

  it("distinguishes an unscored hex from a low-scoring one", () => {
    renderLegend();
    expect(screen.getByText(/not scored/i)).toBeInTheDocument();
  });

  it("explains the hatching as confidence and not as burden", () => {
    renderLegend();
    expect(screen.getByText(/low — read with caution/i)).toBeInTheDocument();
    expect(screen.getByText(/colour is how burdened, texture is how sure/i)).toBeInTheDocument();
  });

  it("leaves the insufficient band off by default", () => {
    renderLegend(false);
    expect(screen.getByRole("checkbox", { name: /insufficient/i })).not.toBeChecked();
  });

  it("reflects the insufficient band being switched on", () => {
    renderLegend(true);
    expect(screen.getByRole("checkbox", { name: /insufficient/i })).toBeChecked();
  });

  it("reports the toggle to the map", async () => {
    const onChange = renderLegend(false);
    await userEvent.click(screen.getByRole("checkbox", { name: /insufficient/i }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("says why an insufficient hex is withheld rather than only that it is", () => {
    renderLegend();
    expect(screen.getByText(/excluded from validation statistics/i)).toBeInTheDocument();
  });
});
