/** WCAG contrast, computed from Tailwind's own palette.
 *
 *  Axe checks contrast in a real browser and cannot in jsdom, which has no
 *  layout and no computed styles — it reports the rule *incomplete*, and a
 *  green axe run says nothing about whether the text is readable. That left
 *  the one WCAG criterion this project most obviously owes, on a tool aimed at
 *  people who are not being well served by anything else, resting on nobody
 *  having checked.
 *
 *  The palette is read from `tailwindcss/theme.css` rather than transcribed,
 *  so the numbers are the ones that ship. Tailwind v4 states them in oklch, so
 *  they are converted here.
 */

/** One `oklch(L% C H)` triple as Tailwind writes it. */
export interface Oklch {
  l: number;
  c: number;
  h: number;
}

const TOKEN = /--color-([a-z]+)-(\d+):\s*oklch\(([\d.]+)%\s+([\d.]+)\s+([\d.]+)\s*\)/g;

/** Every `--color-<name>-<shade>` in a Tailwind theme stylesheet. */
export function parsePalette(css: string): Record<string, Oklch> {
  const out: Record<string, Oklch> = {};
  for (const m of css.matchAll(TOKEN)) {
    out[`${m[1]}-${m[2]}`] = { l: Number(m[3]) / 100, c: Number(m[4]), h: Number(m[5]) };
  }
  return out;
}

/** oklch to linear sRGB, by the Oklab matrices in the colour spec. */
export function oklchToLinearSrgb({ l, c, h }: Oklch): [number, number, number] {
  const hr = (h * Math.PI) / 180;
  const a = c * Math.cos(hr);
  const b = c * Math.sin(hr);

  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;

  const L = l_ ** 3;
  const M = m_ ** 3;
  const S = s_ ** 3;

  return [
    +4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ];
}

/** WCAG relative luminance. Linear sRGB already, so no gamma step. */
export function luminance(colour: Oklch): number {
  const [r, g, b] = oklchToLinearSrgb(colour).map((v) => Math.min(1, Math.max(0, v)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** The WCAG 2.1 contrast ratio between two colours, 1 to 21. */
export function contrastRatio(a: Oklch, b: Oklch): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** WCAG AA: 4.5 for body text, 3.0 for large text and UI components. */
export const AA_BODY = 4.5;
export const AA_LARGE = 3.0;
