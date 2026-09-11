import { useEffect, useRef } from "react";

import {
  COMPONENT_LABELS,
  bandReading,
  confidenceTerms,
  droppedGroups,
  isZeroInflated,
  leadsWithCaveat,
  productOfComponents,
  vintageFor,
  weakestTerm,
  weightedGroupMean,
} from "../lib/score.ts";
import { BAND_LABELS, GROUP_LABELS } from "../lib/types.ts";
import type { ComponentScore, HexDetail, IndicatorValue } from "../lib/types.ts";

function Bar({ percentile, observed }: { percentile: number | null; observed: boolean }) {
  if (!observed || percentile === null) {
    return <span className="text-xs text-slate-400 italic">not observed</span>;
  }
  return (
    <div className="h-2 w-full rounded-sm bg-slate-100">
      <div
        className="h-2 rounded-sm bg-slate-700"
        style={{ width: `${String(Math.max(1, percentile))}%` }}
      />
    </div>
  );
}

function IndicatorRow({
  indicator,
  vintage,
}: {
  indicator: IndicatorValue;
  vintage: string | null;
}) {
  return (
    <li className="grid grid-cols-[1fr_5rem] items-center gap-3 py-1.5">
      <div>
        <div className="text-sm text-slate-800">
          <span className="mr-1.5 font-mono text-xs text-slate-400">{indicator.id}</span>
          {indicator.name}
        </div>
        <Bar percentile={indicator.percentile} observed={indicator.observed} />
        <div className="mt-0.5 text-xs text-slate-500">
          {indicator.source}
          {vintage && <span> &middot; {vintage}</span>}
        </div>
        {isZeroInflated(indicator) && (
          // Methodology section 9 requires this on the panel rather than
          // smoothed over. Without it the percentile reads as a ranking, when
          // for a hex with nothing nearby it is only the size of the zero block.
          <p className="mt-0.5 text-xs text-amber-800">
            No qualifying facility within 10 km. This percentile reflects how many other
            hexagons are also at zero, not how this one compares on burden.
          </p>
        )}
      </div>
      <div className="text-right text-sm tabular-nums text-slate-600">
        {indicator.observed && indicator.percentile !== null
          ? `${indicator.percentile.toFixed(0)}th`
          : "—"}
      </div>
    </li>
  );
}

/** Methodology section 10, steps 1 to 3, for one component. Each group's mean
 *  percentile, the weight it carries, and the weighted mean they produce. */
function ComponentWaterfall({ component }: { component: ComponentScore }) {
  const raw = weightedGroupMean(component.groups);
  const dropped = droppedGroups(component.groups);

  return (
    <section className="mb-4">
      <h4 className="flex items-baseline justify-between text-sm font-semibold text-slate-900">
        <span>{COMPONENT_LABELS[component.component]}</span>
        <span className="tabular-nums text-slate-600">{component.score.toFixed(1)} / 10</span>
      </h4>

      <ul className="mt-1.5">
        {component.groups.map((group) => (
          <li
            key={group.group}
            className="grid grid-cols-[1fr_3rem_3.5rem] items-center gap-2 py-1 text-sm"
          >
            <div>
              <div className="text-slate-800">{GROUP_LABELS[group.group]}</div>
              <div className="text-xs text-slate-500">
                {group.indicators_present} of {group.indicators_required} indicators needed
                {!group.computable && " — not computable, dropped"}
              </div>
            </div>
            <div className="text-right text-xs tabular-nums text-slate-500">
              &times;{group.weight.toFixed(1)}
            </div>
            <div className="text-right text-sm tabular-nums text-slate-700">
              {group.computable && group.mean_percentile !== null
                ? `${group.mean_percentile.toFixed(0)}th`
                : "—"}
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-1 border-t border-slate-200 pt-1.5 text-xs text-slate-600">
        {raw === null ? (
          <p>No group in this component was computable.</p>
        ) : (
          <p>
            Weighted mean of the groups above:{" "}
            <span className="tabular-nums text-slate-800">{raw.toFixed(1)}th percentile</span>,
            rescaled to{" "}
            <span className="tabular-nums text-slate-800">{component.score.toFixed(1)} / 10</span>.
          </p>
        )}
        {dropped.length > 0 && (
          <p className="mt-1">
            {dropped.map((g) => GROUP_LABELS[g.group]).join(" and ")}{" "}
            {dropped.length === 1 ? "was" : "were"} left out of that mean rather than counted as
            zero, which would have read as an absence of burden.
          </p>
        )}
      </div>
    </section>
  );
}

function ConfidenceBreakdown({ hex }: { hex: HexDetail }) {
  const terms = confidenceTerms(hex.confidence);
  const weakest = weakestTerm(hex.confidence);

  return (
    <section className="mb-5">
      <h4 className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
        Confidence
      </h4>
      <p className="text-sm text-slate-700">{bandReading(hex.confidence.band)}</p>

      <ul className="mt-2">
        {terms.map((term) => (
          <li
            key={term.id}
            className="grid grid-cols-[1fr_2.5rem_3rem] items-center gap-2 py-1 text-sm"
          >
            <div>
              <div className="text-slate-800">{term.label}</div>
              <div className="text-xs text-slate-500">{term.meaning}</div>
            </div>
            <div className="text-right text-xs tabular-nums text-slate-500">
              &times;{term.weight.toFixed(2)}
            </div>
            <div className="text-right tabular-nums text-slate-700">{term.value.toFixed(2)}</div>
          </li>
        ))}
      </ul>

      <p className="mt-2 text-xs leading-relaxed text-slate-500">
        The four combine as a weighted geometric mean, not an average, so one weak term is not
        smoothed away by three healthy ones. The weakest here is{" "}
        <span className="text-slate-700">{weakest.label.toLowerCase()}</span> at{" "}
        <span className="tabular-nums text-slate-700">{weakest.value.toFixed(2)}</span>
        {weakest.id === "monitor" && hex.confidence.nearest_monitor_km !== null && (
          <>
            {" "}
            — the nearest PM2.5 monitor is{" "}
            <span className="tabular-nums text-slate-700">
              {hex.confidence.nearest_monitor_km.toFixed(0)} km
            </span>{" "}
            away
          </>
        )}
        . Confidence says how well supported the score is, never how severe the burden is.
      </p>
    </section>
  );
}

export default function HexPanel({ hex, onClose }: { hex: HexDetail; onClose: () => void }) {
  const groups = Object.keys(GROUP_LABELS) as (keyof typeof GROUP_LABELS)[];
  const dropped = hex.indicators.filter((i) => !i.observed).length;
  const product = productOfComponents(hex.components);
  const caveatLeads = leadsWithCaveat(hex.confidence.band);

  const panel = useRef<HTMLElement>(null);

  // Selecting a hex moves the reader here, so the keyboard goes with them.
  // Without this, tabbing after a click continues from the map and walks the
  // whole panel in reverse before reaching anything in it.
  useEffect(() => {
    panel.current?.focus();
  }, [hex.h3]);

  return (
    <aside
      ref={panel}
      tabIndex={-1}
      aria-label={`Details for hexagon ${hex.h3}`}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
      className="flex h-full w-full flex-col overflow-y-auto bg-white focus:outline-none md:border-l md:border-slate-200"
    >
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-xs text-slate-400">{hex.h3}</div>
            <h2 className="text-lg font-semibold text-slate-900">
              {hex.parish ? `${hex.parish} Parish` : hex.state}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100 focus:ring-2 focus:ring-slate-400 focus:outline-none"
            aria-label="Close panel"
          >
            Close
          </button>
        </div>

        {/* Section 12: for the low and insufficient bands the caveat leads,
            rather than sitting under a number the reader has already taken in. */}
        {caveatLeads && (
          <p className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            {bandReading(hex.confidence.band)}
          </p>
        )}

        {hex.score === null ? (
          <p className="mt-3 text-sm text-slate-600">
            Not scored: {hex.no_score_reason?.replace(/_/g, " ")}
          </p>
        ) : (
          <div className="mt-3 flex items-baseline gap-3">
            <span className="text-3xl font-semibold tabular-nums text-slate-900">
              {hex.score.toFixed(1)}
            </span>
            <span className="text-sm text-slate-600">
              {hex.percentile?.toFixed(0)}th percentile statewide
            </span>
          </div>
        )}

        <p className="mt-2 text-xs text-slate-500">
          {BAND_LABELS[hex.confidence.band]} ({hex.confidence.value.toFixed(2)})
          {dropped > 0 && ` · ${String(dropped)} of ${String(hex.indicators.length)} indicators unavailable`}
        </p>
      </header>

      <div className="px-5 py-4">
        {hex.components.length > 0 && (
          <section className="mb-5">
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
              How this score was reached
            </h3>

            {hex.components.map((component) => (
              <ComponentWaterfall key={component.component} component={component} />
            ))}

            <p className="mb-3 text-xs leading-relaxed text-slate-500">
              Each component is rescaled against the highest value anywhere in the state. That
              statewide maximum is not part of this response, so the rescaling step is the one
              part of the arithmetic above that cannot be checked here.
            </p>

            {product !== null && hex.components.length === 2 && (
              <div className="rounded bg-slate-50 px-3 py-2 text-sm text-slate-700">
                <p className="tabular-nums">
                  {hex.components.map((c) => c.score.toFixed(1)).join(" × ")} ={" "}
                  <span className="font-semibold text-slate-900">{product.toFixed(1)}</span>
                </p>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">
                  The two components multiply rather than add. A hexagon in the 95th percentile
                  for pollution and the 20th for vulnerability scores about 19; one in the 60th
                  for both scores about 36. The second is higher, and that is the model working
                  as designed: burden and vulnerability compound rather than offset.
                </p>
              </div>
            )}
          </section>
        )}

        <ConfidenceBreakdown hex={hex} />

        {groups.map((group) => {
          const rows = hex.indicators.filter((i) => i.group === group);
          if (rows.length === 0) return null;
          return (
            <section key={group} className="mb-5">
              <h4 className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                {GROUP_LABELS[group]}
              </h4>
              <ul className="divide-y divide-slate-100">
                {rows.map((i) => (
                  <IndicatorRow
                    key={i.id}
                    indicator={i}
                    vintage={vintageFor(i, hex.data_vintage)}
                  />
                ))}
              </ul>
            </section>
          );
        })}

        {hex.facilities.length > 0 && (
          <section className="mb-5">
            <h4 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
              Contributing facilities
            </h4>
            <ul className="space-y-2">
              {hex.facilities.map((f) => (
                <li key={f.registry_id} className="text-sm">
                  <a
                    href={f.echo_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-slate-800 underline decoration-slate-300 hover:decoration-slate-800 focus:ring-2 focus:ring-slate-400 focus:outline-none"
                  >
                    {f.name}
                  </a>
                  <div className="text-xs text-slate-500">
                    {f.program} &middot; {f.distance_km.toFixed(1)} km
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="mb-5">
          <h4 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Who lives here
          </h4>
          <p className="text-sm text-slate-700">
            Population {hex.demographics.population.toLocaleString()}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Recorded and displayed, never an input to the score. Keeping race out of the
            arithmetic is what makes the disparity finding an independent result.
          </p>
        </section>

        <footer className="border-t border-slate-200 pt-3 text-xs leading-relaxed text-slate-500">
          A high score describes modeled exposure, nearby permitted sources, and a vulnerable
          population. It is not a finding of wrongdoing by any operator. Percentiles are
          Louisiana percentiles. Methodology version {hex.methodology_version}.
        </footer>
      </div>
    </aside>
  );
}
