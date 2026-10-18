import { ChevronRight } from "lucide-react";
import { useId, useState } from "react";

import { cn } from "@/lib/utils.ts";
import {
  HATCH_ANGLE_DEG,
  LEGEND_CLASSES,
  NO_SCORE_COLOR,
  NO_SCORE_OPACITY,
  blendOnWhite,
} from "../lib/ramp.ts";
import { Checkbox } from "./ui/checkbox.tsx";
import { Separator } from "./ui/separator.tsx";

/** A swatch as the map draws it. The fill is painted at `FILL_OPACITY` so the
 *  basemap shows through, and an opaque swatch of the same hex is visibly
 *  darker than the hexagons it is meant to identify.
 *
 *  It stays a `span` carrying an inline `background-color`: `Legend.test.tsx`
 *  reads every `span[style]` back and asserts each one is the blended colour
 *  rather than the raw ramp entry. */
function Swatch({ color, opacity }: { color: string; opacity?: number }) {
  return (
    <span
      className="h-4 w-6 shrink-0 rounded-sm ring-1 ring-black/15"
      style={{ backgroundColor: blendOnWhite(color, opacity) }}
      aria-hidden="true"
    />
  );
}

/** The hatch, as an inline SVG pattern rather than the canvas image the map
 *  uses. Two renderers, one appearance: the angle, spacing and weight are the
 *  same numbers on both sides, so the swatch matches the fill. */
function HatchSwatch({ color }: { color: string }) {
  // The id is generated rather than fixed, so a second legend on one page
  // cannot collide with the first and hand both of them one pattern.
  const patternId = useId();
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-6 shrink-0 rounded-sm" aria-hidden="true">
      <defs>
        <pattern
          id={patternId}
          width="8"
          height="8"
          patternUnits="userSpaceOnUse"
          patternTransform={`rotate(${String(HATCH_ANGLE_DEG)})`}
        >
          <rect width="8" height="8" fill={blendOnWhite(color)} />
          <line x1="0" y1="0" x2="0" y2="8" stroke="#282828" strokeOpacity="0.67" strokeWidth="2" />
        </pattern>
      </defs>
      <rect width="16" height="16" fill={`url(#${patternId})`} />
    </svg>
  );
}

/** A class's range in words. "90–100 (top decile)" was opaque to anyone
 *  unfamiliar with percentiles and deciles. */
const LEGEND_WORDS: Record<number, string> = {
  0: "Least burdened 20%",
  20: "Below average",
  40: "Around average",
  60: "Above average",
  80: "High",
  90: "Most burdened 10%",
};

function legendWording(from: number, to: number): string {
  return LEGEND_WORDS[from] ?? `${String(from)}–${String(to)}%`;
}

/** A small-caps label for one block of the legend. */
function GroupLabel({ children, className }: { children: string; className?: string }) {
  return (
    <h3
      className={cn(
        "text-[0.6875rem] font-semibold tracking-[0.06em] text-muted-foreground uppercase",
        className,
      )}
    >
      {children}
    </h3>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <li className="flex items-center gap-2.5 text-xs text-body">{children}</li>;
}

interface Props {
  showInsufficient: boolean;
  onShowInsufficientChange: (next: boolean) => void;
}

export default function Legend({ showInsufficient, onShowInsufficientChange }: Props) {
  // Collapsed on small screens by default. The legend has to be visible, but on
  // a phone a permanently open one covers the map it is explaining.
  //
  // Hand-rolled rather than a Radix Collapsible: above `sm` the content is
  // open unconditionally, and a Collapsible's closed state sets `hidden` on
  // the content, which a responsive `display` utility then has to win a
  // specificity tie against. One piece of state and two classes is the
  // behaviour this needs, stated outright.
  const [open, setOpen] = useState(false);
  const toggleId = useId();

  return (
    <section
      aria-label="Map legend"
      // A fixed width on desktop. Without one the box grows to its longest line
      // of help text and covered a third of the map.
      className="pointer-events-auto absolute bottom-6 left-2 z-10 max-w-[calc(100vw-1rem)] sm:w-64
                 overflow-hidden rounded-lg border border-border bg-card/95 shadow-lg
                 ring-1 ring-black/5 backdrop-blur-sm sm:bottom-8 sm:left-3"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-2.5 text-left text-[0.6875rem]
                   font-semibold tracking-[0.06em] text-muted-foreground uppercase
                   hover:text-foreground sm:hidden"
      >
        Legend
        <ChevronRight
          aria-hidden="true"
          className={cn("size-3.5 transition-transform", open && "rotate-90")}
        />
      </button>

      <div className={cn(open ? "block" : "hidden", "px-3.5 pt-1 pb-3.5 sm:block sm:pt-3.5")}>
        <GroupLabel className="hidden sm:block">Pollution burden</GroupLabel>
        <p className="mt-0.5 text-[0.6875rem] text-faint">Compared with the rest of Louisiana</p>

        <ul className="mt-2.5 flex flex-col gap-1">
          {LEGEND_CLASSES.map((cls) => (
            <Row key={cls.label}>
              <Swatch color={cls.color} />
              <span>
                {legendWording(cls.from, cls.to)}
                {/* The range too, for a reader who wants the number; the
                    first and last words already carry theirs. */}
                {cls.from !== 0 && cls.to !== 100 && (
                  <span className="text-faint">
                    {" "}
                    ({cls.from}–{cls.to}%)
                  </span>
                )}
              </span>
            </Row>
          ))}
          <Row>
            <Swatch color={NO_SCORE_COLOR} opacity={NO_SCORE_OPACITY} />
            {/* Solid, and the map draws it solid: an unscored hexagon is not
                hatched, because hatching would say its score is poorly
                supported when it has no score to support. */}
            <span>
              Not ranked <span className="text-faint">(too few people live there)</span>
            </span>
          </Row>
        </ul>

        <Separator className="mt-3.5" />

        <GroupLabel className="mt-3">How sure we are</GroupLabel>
        <ul className="mt-2 flex flex-col gap-1.5">
          <Row>
            <Swatch color={LEGEND_CLASSES[3].color} />
            <span>Good data</span>
          </Row>
          <Row>
            <HatchSwatch color={LEGEND_CLASSES[3].color} />
            <span>Limited data: a rough guide</span>
          </Row>
        </ul>

        {/* aria-labelledby rather than a wrapping label: the checkbox is a
            Radix button underneath, and naming it from an explicit id is what
            makes the accessible name independent of how it is nested. */}
        <div className="mt-3 flex items-start gap-2.5">
          <Checkbox
            id={toggleId}
            checked={showInsufficient}
            onCheckedChange={(next) => onShowInsufficientChange(next === true)}
            aria-labelledby={`${toggleId}-label`}
            className="mt-0.5"
          />
          <label htmlFor={toggleId} className="text-xs text-body">
            <span id={`${toggleId}-label`}>Show areas with too little data</span>
            <span className="mt-0.5 block text-[0.6875rem] leading-snug text-faint">
              Ranked, but with too little data for us to stand behind. We leave them out of our
              accuracy checks and you can&apos;t draft documents from them.
            </span>
          </label>
        </div>

        <p className="mt-3 max-w-[18rem] border-t border-border pt-2.5 text-[0.6875rem] leading-snug text-faint">
          Colour shows how burdened a place is; stripes mean we&apos;re less sure. A pale colour
          means less burdened. It never means missing data.
        </p>
      </div>
    </section>
  );
}
