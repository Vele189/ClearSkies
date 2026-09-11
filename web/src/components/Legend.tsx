import { useState } from "react";

import { LEGEND_CLASSES, NO_SCORE_COLOR } from "../lib/ramp.ts";

/** The hatch, as an inline SVG pattern rather than the canvas image the map
 *  uses. Two renderers, one appearance: the angle, spacing and weight are the
 *  same numbers on both sides, so the swatch matches the fill. */
function HatchSwatch({ color }: { color: string }) {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-6 shrink-0 rounded-xs" aria-hidden="true">
      <defs>
        <pattern
          id="legend-hatch"
          width="8"
          height="8"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(-45)"
        >
          <rect width="8" height="8" fill={color} />
          <line x1="0" y1="0" x2="0" y2="8" stroke="#282828" strokeOpacity="0.67" strokeWidth="2" />
        </pattern>
      </defs>
      <rect width="16" height="16" fill="url(#legend-hatch)" />
    </svg>
  );
}

interface Props {
  showInsufficient: boolean;
  onShowInsufficientChange: (next: boolean) => void;
}

export default function Legend({ showInsufficient, onShowInsufficientChange }: Props) {
  // Collapsed on small screens by default. The legend has to be visible, but on
  // a phone a permanently open one covers the map it is explaining.
  const [open, setOpen] = useState(false);

  return (
    <section
      aria-label="Map legend"
      className="pointer-events-auto absolute bottom-6 left-2 z-10 max-w-[calc(100vw-1rem)] rounded-md border border-slate-200 bg-white/95 text-slate-900 shadow-sm backdrop-blur-sm sm:bottom-8 sm:left-3"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-semibold tracking-wide text-slate-700 uppercase sm:hidden"
      >
        Legend
        <span aria-hidden="true" className="text-slate-400">
          {open ? "▾" : "▸"}
        </span>
      </button>

      <div className={`${open ? "block" : "hidden"} px-3 pt-1 pb-3 sm:block sm:pt-3`}>
        <h2 className="hidden text-xs font-semibold tracking-wide text-slate-700 uppercase sm:block">
          Burden score
        </h2>
        <p className="mt-0.5 text-[0.6875rem] text-slate-500">Louisiana percentile</p>

        <ul className="mt-2 flex flex-col gap-0.5">
          {LEGEND_CLASSES.map((cls) => (
            <li key={cls.label} className="flex items-center gap-2 text-xs text-slate-700">
              <span
                className="h-4 w-6 shrink-0 rounded-xs border border-black/10"
                style={{ backgroundColor: cls.color }}
                aria-hidden="true"
              />
              <span className="tabular-nums">
                {cls.label}
                {cls.from === 90 && <span className="text-slate-500"> (top decile)</span>}
              </span>
            </li>
          ))}
          <li className="flex items-center gap-2 text-xs text-slate-700">
            <span
              className="h-4 w-6 shrink-0 rounded-xs border border-black/10"
              style={{ backgroundColor: NO_SCORE_COLOR }}
              aria-hidden="true"
            />
            <span>Not scored</span>
          </li>
        </ul>

        <h3 className="mt-3 border-t border-slate-200 pt-2 text-xs font-semibold tracking-wide text-slate-700 uppercase">
          Confidence
        </h3>
        <ul className="mt-1.5 flex flex-col gap-1">
          <li className="flex items-center gap-2 text-xs text-slate-700">
            <span
              className="h-4 w-6 shrink-0 rounded-xs border border-black/10"
              style={{ backgroundColor: LEGEND_CLASSES[3].color }}
              aria-hidden="true"
            />
            <span>High or moderate</span>
          </li>
          <li className="flex items-center gap-2 text-xs text-slate-700">
            <HatchSwatch color={LEGEND_CLASSES[3].color} />
            <span>Low — read with caution</span>
          </li>
        </ul>

        <label className="mt-2 flex items-start gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            checked={showInsufficient}
            onChange={(event) => onShowInsufficientChange(event.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-slate-700"
          />
          <span>
            Show insufficient-data hexes
            <span className="mt-0.5 block text-[0.6875rem] leading-snug text-slate-500">
              Scored, but not well enough for us to stand behind. Excluded from validation
              statistics and from the drafting assistant.
            </span>
          </span>
        </label>

        <p className="mt-2 text-[0.6875rem] leading-snug text-slate-500">
          Colour is how burdened, texture is how sure. A pale hex is a low percentile, never a
          missing measurement.
        </p>
      </div>
    </section>
  );
}
