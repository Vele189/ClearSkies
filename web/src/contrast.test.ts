/** Colour contrast, the WCAG AA criterion axe cannot check here (CS-401).
 *
 *  Every pair below is one the UI actually renders. The palette is read from
 *  Tailwind's shipped theme, so this measures what the browser will draw
 *  rather than what a transcribed hex value claims.
 *
 *  A tool aimed at people who are not well served by anything else does not
 *  get to leave this one to "nobody complained".
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

import { AA_BODY, AA_LARGE, contrastRatio, parsePalette, type Oklch } from "./lib/contrast.ts";

const require = createRequire(import.meta.url);
const THEME = readFileSync(require.resolve("tailwindcss/theme.css"), "utf8");
const PALETTE = parsePalette(THEME);

const WHITE: Oklch = { l: 1, c: 0, h: 0 };

function colour(token: string): Oklch {
  if (token === "white") return WHITE;
  const found = PALETTE[token];
  if (!found) throw new Error(`no such Tailwind colour: ${token}`);
  return found;
}

/** [foreground, background, where it is rendered] */
const BODY_TEXT: [string, string, string][] = [
  ["slate-900", "white", "headings, panel and pages"],
  ["slate-700", "white", "body copy on every written page"],
  ["slate-700", "slate-50", "footer disclaimer"],
  ["slate-600", "white", "nav, secondary labels"],
  ["slate-600", "slate-50", "footer secondary"],
  ["slate-500", "white", "hex index, indicator ids, the not-observed label"],
  ["slate-500", "slate-50", "muted detail on a tinted panel"],
  ["sky-800", "white", "links"],
  ["amber-900", "amber-50", "the degraded-deployment banner"],
  ["emerald-900", "emerald-50", "provenance: loaded"],
  ["rose-900", "rose-50", "provenance: failed"],
];

/** Non-text pairs WCAG 1.4.11 actually covers, held to 3.0.
 *
 *  Not dividers and card borders. 1.4.11 covers the parts of a control needed
 *  to identify it and graphics needed to understand the content; a 1px rule
 *  between two sections is decorative, and asserting 3:1 on it would fail a
 *  design that meets the standard. `slate-200` borders are therefore absent
 *  here on purpose rather than by oversight.
 *
 *  `slate-400` is absent too, for the opposite reason: it measured 2.63:1 and
 *  was carrying real text -- the "not observed" label that section 11 requires
 *  a reader always sees, the indicator ids and the hexagon index. Those moved
 *  to `slate-500`, which is in the body list below where they belong. What is
 *  still drawn in `slate-400` is two `aria-hidden` bullets.
 */
const LARGE_OR_UI: [string, string, string][] = [
  ["slate-500", "white", "the search input's border, which identifies the control"],
];

describe("WCAG AA contrast", () => {
  it.each(BODY_TEXT)("%s on %s (%s) is readable as body text", (fg, bg) => {
    expect(contrastRatio(colour(fg), colour(bg))).toBeGreaterThanOrEqual(AA_BODY);
  });

  it.each(LARGE_OR_UI)("%s on %s (%s) clears the non-text bar", (fg, bg) => {
    expect(contrastRatio(colour(fg), colour(bg))).toBeGreaterThanOrEqual(AA_LARGE);
  });

  it("reads the palette that actually ships rather than a transcription", () => {
    // If Tailwind changes its format this suite must fail loudly rather than
    // silently measure an empty palette.
    expect(Object.keys(PALETTE).length).toBeGreaterThan(200);
    expect(PALETTE["slate-700"]).toBeDefined();
  });

  it("agrees with a known contrast ratio", () => {
    // Black on white is 21:1 exactly, which is the one value every
    // implementation must agree on.
    expect(contrastRatio({ l: 0, c: 0, h: 0 }, WHITE)).toBeCloseTo(21, 1);
  });
});
