import { CONFIDENCE, RAMP, UNSCORED_COLOR } from "../lib/ramp.ts";

/** The hatch the map draws over low-confidence hexes, as an inline SVG swatch.
 *  Drawn from the same idea as the map's fill pattern so the legend shows the
 *  reader the thing they are actually looking at. */
function HatchSwatch() {
  return (
    <svg width="24" height="14" aria-hidden="true" className="shrink-0 rounded-sm">
      <defs>
        <pattern id="legend-hatch" width="4" height="4" patternUnits="userSpaceOnUse">
          <path d="M0 4 L4 0" stroke="#1e293b" strokeWidth="1" opacity="0.67" />
        </pattern>
      </defs>
      <rect width="24" height="14" fill="#fd8d3c" />
      <rect width="24" height="14" fill="url(#legend-hatch)" />
    </svg>
  );
}

interface Props {
  /** Whether the insufficient-confidence hexes are currently drawn. */
  showUntrusted: boolean;
  onToggleUntrusted: (next: boolean) => void;
}

/**
 * What the colours mean, on screen rather than in the documentation.
 *
 * A choropleth without a legend is a picture. The confidence treatments are in
 * here too, because section 12 draws them and a reader who cannot tell a hatched
 * hex from a solid one is reading a map that is quietly lying to them about how
 * much it knows.
 */
export default function Legend({ showUntrusted, onToggleUntrusted }: Props) {
  const gradient = `linear-gradient(to right, ${RAMP.map(
    ({ at, color }) => `${color} ${at}%`,
  ).join(", ")})`;

  return (
    <div className="pointer-events-auto absolute bottom-6 left-3 z-10 w-64 rounded-lg border border-slate-200 bg-white/95 p-3 text-xs shadow-lg backdrop-blur">
      <p className="font-semibold text-slate-900">Burden score</p>
      <p className="mt-0.5 text-[11px] leading-snug text-slate-500">
        Statewide percentile. A Louisiana 90th is not a national 90th.
      </p>

      <div className="mt-2 h-3 w-full rounded" style={{ background: gradient }} />
      <div className="mt-1 flex justify-between text-[11px] text-slate-500">
        <span>0</span>
        <span>50</span>
        <span className="font-medium text-slate-700">90</span>
        <span>100</span>
      </div>
      <p className="mt-1 text-[11px] text-slate-500">
        The 90th is the top decile the validation protocol gates on.
      </p>

      <p className="mt-3 font-semibold text-slate-900">Confidence</p>
      <ul className="mt-1 space-y-1.5 text-[11px] text-slate-600">
        <li className="flex items-center gap-2">
          <span
            className="h-3.5 w-6 shrink-0 rounded-sm"
            style={{ backgroundColor: "#fd8d3c" }}
            aria-hidden="true"
          />
          <span>High or moderate, drawn plainly</span>
        </li>
        <li className="flex items-center gap-2">
          <HatchSwatch />
          <span>Low, hatched</span>
        </li>
        <li className="flex items-center gap-2">
          <span
            className="h-3.5 w-6 shrink-0 rounded-sm border border-slate-300"
            style={{ backgroundColor: UNSCORED_COLOR }}
            aria-hidden="true"
          />
          <span>Not scored; the panel says why</span>
        </li>
      </ul>

      <label className="mt-3 flex items-start gap-2 text-[11px] text-slate-600">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={showUntrusted}
          onChange={(event) => onToggleUntrusted(event.target.checked)}
        />
        <span>
          Show hexes below {CONFIDENCE.insufficient.toFixed(2)} confidence. These are
          excluded from validation statistics and cannot produce a document.
        </span>
      </label>

      <p className="mt-2 text-[11px] text-slate-400">
        Confidence is how well supported a score is, never how severe the burden is.
      </p>
    </div>
  );
}
