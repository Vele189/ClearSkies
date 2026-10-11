/** Colour contrast, the WCAG AA criterion axe cannot check here (CS-401).
 *
 *  Every pair below is one the UI actually renders, named with the semantic
 *  token the component writes rather than the Tailwind shade behind it. The
 *  chain is: the component says `text-body` on `bg-sunken`; `src/index.css`
 *  aliases `--color-body` to a palette entry; the palette is read out of the
 *  stylesheet Tailwind ships. So this measures what the browser will draw, and
 *  it keeps measuring it after a redesign repoints a token.
 *
 *  Two things it still does not cover, and neither should be read as covered.
 *  The ramp's own six classes are asserted in `lib/ramp.test.ts`, which holds
 *  the lightness monotonicity that makes them colourblind-safe. And whether
 *  the low-confidence hatch stays distinguishable from the ramp is a judgement
 *  about a rendered map, which no DOM assertion reaches. CS-401's manual
 *  screen-reader and browser pass is for exactly these.
 *
 *  A tool aimed at people who are not well served by anything else does not
 *  get to leave this one to "nobody complained".
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

import {
  AA_BODY,
  AA_LARGE,
  contrastRatio,
  parsePalette,
  parseSemanticAliases,
  type Oklch,
} from "./lib/contrast.ts";

const require = createRequire(import.meta.url);
const THEME = readFileSync(require.resolve("tailwindcss/theme.css"), "utf8");
const PALETTE = parsePalette(THEME);
const ALIASES = parseSemanticAliases(readFileSync("src/index.css", "utf8"));

const WHITE: Oklch = { l: 1, c: 0, h: 0 };

/** A semantic token, resolved through the theme to a measurable colour. */
function colour(token: string): Oklch {
  const target = ALIASES[token];
  if (target === undefined) {
    throw new Error(`no such semantic colour in index.css: --color-${token}`);
  }
  if (target === "white") return WHITE;
  const found = PALETTE[target];
  if (!found) throw new Error(`--color-${token} points at a missing Tailwind colour: ${target}`);
  return found;
}

/** [foreground token, background token, where it is rendered] */
const BODY_TEXT: [string, string, string][] = [
  // Headings and the figures a reader lands on first.
  ["foreground", "card", "headings, the hexagon score, panel and page titles"],
  ["foreground", "sunken", "the multiplication box, draft panel headings"],
  // Running text.
  ["body", "card", "prose on every written page, the panel's rows"],
  ["body", "sunken", "the multiplication note, the draft panel's body"],
  ["body", "secondary", "a citation with no public page, rendered as a chip"],
  // Labels and secondary rows.
  ["muted-foreground", "card", "nav, card descriptions, section labels"],
  ["muted-foreground", "sunken", "the footer disclaimer, the draft blurb"],
  // The quietest text that is still text.
  ["faint", "card", "hexagon index, indicator ids, the not-observed label"],
  ["faint", "sunken", "muted detail inside a tinted panel"],
  // Links.
  ["link", "card", "links in running text, facility names"],
  ["link", "sunken", "links inside the draft panel"],
  ["link", "citation-surface", "a citation chip that is followable"],
  // Inverted and tinted surfaces.
  ["primary-foreground", "primary", "the default button"],
  ["secondary-foreground", "secondary", "the default badge"],
  // Status, shared by the provenance page, the banner and the draft notices.
  ["warn-foreground", "warn-surface", "degraded deployment, caveats, the draft notice"],
  ["ok-foreground", "ok-surface", "provenance: loaded"],
  ["bad-foreground", "bad-surface", "provenance: failed"],
];

/** Non-text pairs WCAG 1.4.11 actually covers, held to 3.0.
 *
 *  Not dividers and card borders. 1.4.11 covers the parts of a control needed
 *  to identify it and graphics needed to understand the content; a 1px rule
 *  between two sections is decorative, and asserting 3:1 on it would fail a
 *  design that meets the standard. `border` and `border-strong` are therefore
 *  absent here on purpose rather than by oversight, and so are the badge rings.
 *
 *  What is here is every border that *is* a control's own outline, the focus
 *  indicator, and the one graphic that carries a value.
 */
const LARGE_OR_UI: [string, string, string][] = [
  ["input", "card", "the search input, the checkbox, and every outlined button"],
  ["ring", "card", "the focus indicator, on every surface the app has"],
  ["ring", "sunken", "the focus indicator over a tinted panel"],
  ["primary", "card", "a checked checkbox, and the current nav item's rule"],
  ["body", "secondary", "the indicator bar's fill against its track"],
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

  it("reads the theme's own aliases rather than a second copy of them", () => {
    // Same argument one layer up: an empty alias map would make every
    // assertion above throw rather than pass, but a *partial* one would not,
    // so the shape is checked outright.
    expect(Object.keys(ALIASES).length).toBeGreaterThan(15);
    expect(ALIASES["body"]).toBe("slate-700");
    expect(ALIASES["background"]).toBe("white");
  });

  it("holds every semantic text token to the body-text bar on both surfaces", () => {
    // The list above is hand-kept, so this is the backstop: any token whose
    // name ends in `-foreground`, plus the four this project adds, has to be
    // legible on at least one declared surface. A token that is legible
    // nowhere is a token that should not exist.
    const text = Object.keys(ALIASES).filter(
      (t) => t.endsWith("foreground") || ["body", "faint", "link"].includes(t),
    );
    expect(text.length).toBeGreaterThan(5);
    for (const token of text) {
      const best = ["card", "sunken", "secondary", "primary", "warn-surface", "ok-surface", "bad-surface", "citation-surface"]
        .map((bg) => contrastRatio(colour(token), colour(bg)))
        .reduce((a, b) => Math.max(a, b));
      expect(best, `--color-${token} is not legible on any declared surface`).toBeGreaterThanOrEqual(
        AA_BODY,
      );
    }
  });

  it("agrees with a known contrast ratio", () => {
    // Black on white is 21:1 exactly, which is the one value every
    // implementation must agree on.
    expect(contrastRatio({ l: 0, c: 0, h: 0 }, WHITE)).toBeCloseTo(21, 1);
  });
});
