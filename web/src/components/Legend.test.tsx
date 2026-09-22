import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HATCH_ANGLE_DEG, LEGEND_CLASSES, blendOnWhite } from "../lib/ramp.ts";
import Legend from "./Legend.tsx";

/** jsdom reports a style colour as `rgb(r, g, b)`, so the expectations are
 *  written in the ramp's own notation and converted here. */
function rgb(hex: string): string {
  const channel = (start: number) => parseInt(hex.slice(start, start + 2), 16);
  return `rgb(${String(channel(1))}, ${String(channel(3))}, ${String(channel(5))})`;
}

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

  it("paints its swatches the way the map paints the fill", () => {
    // The map draws the fill at FILL_OPACITY over the basemap. A swatch at full
    // opacity is darker than any hexagon it labels, so the reader matches the
    // colour they see to the class below the one they are looking at.
    const { container } = render(
      <Legend showInsufficient={false} onShowInsufficientChange={vi.fn()} />,
    );
    const swatches = [...container.querySelectorAll("span[style]")].map(
      (node) => (node as HTMLElement).style.backgroundColor,
    );
    for (const cls of LEGEND_CLASSES) {
      expect(swatches).toContain(rgb(blendOnWhite(cls.color)));
      expect(swatches).not.toContain(rgb(cls.color));
    }
  });

  it("hatches its confidence swatch the way the map hatches the fill", () => {
    // Both renderers read HATCH_ANGLE_DEG. Leaning opposite ways made the
    // legend's texture a different texture from the map's.
    const { container } = render(
      <Legend showInsufficient={false} onShowInsufficientChange={vi.fn()} />,
    );
    const pattern = container.querySelector("pattern");
    expect(pattern?.getAttribute("patternTransform")).toBe(`rotate(${String(HATCH_ANGLE_DEG)})`);
  });

  it("says why an insufficient hex is withheld rather than only that it is", () => {
    renderLegend();
    expect(screen.getByText(/excluded from validation statistics/i)).toBeInTheDocument();
  });
});
