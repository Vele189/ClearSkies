import { BAND_LABELS, GROUP_LABELS } from "../lib/types.ts";
import type { HexDetail, IndicatorValue } from "../lib/types.ts";

function Bar({ percentile, observed }: { percentile: number | null; observed: boolean }) {
  if (!observed || percentile === null) {
    return <span className="text-xs text-slate-400 italic">not observed</span>;
  }
  return (
    <div className="h-2 w-full rounded-sm bg-slate-100">
      <div
        className="h-2 rounded-sm bg-slate-700"
        style={{ width: `${Math.max(1, percentile)}%` }}
      />
    </div>
  );
}

function IndicatorRow({ indicator }: { indicator: IndicatorValue }) {
  return (
    <li className="grid grid-cols-[1fr_5rem] items-center gap-3 py-1.5">
      <div>
        <div className="text-sm text-slate-800">
          <span className="mr-1.5 font-mono text-xs text-slate-400">{indicator.id}</span>
          {indicator.name}
        </div>
        <Bar percentile={indicator.percentile} observed={indicator.observed} />
      </div>
      <div className="text-right text-sm tabular-nums text-slate-600">
        {indicator.observed && indicator.percentile !== null
          ? `${indicator.percentile.toFixed(0)}th`
          : "—"}
      </div>
    </li>
  );
}

export default function HexPanel({ hex, onClose }: { hex: HexDetail; onClose: () => void }) {
  const groups = Object.keys(GROUP_LABELS) as (keyof typeof GROUP_LABELS)[];
  const dropped = hex.indicators.filter((i) => !i.observed).length;

  return (
    <aside className="flex h-full w-full flex-col overflow-y-auto border-l border-slate-200 bg-white">
      <header className="sticky top-0 border-b border-slate-200 bg-white px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-xs text-slate-400">{hex.h3}</div>
            <h2 className="text-lg font-semibold text-slate-900">
              {hex.parish ? `${hex.parish} Parish` : hex.state}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
            aria-label="Close panel"
          >
            Close
          </button>
        </div>

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
          {dropped > 0 && ` · ${dropped} of ${hex.indicators.length} indicators unavailable`}
        </p>
      </header>

      <div className="px-5 py-4">
        {hex.components.map((component) => (
          <section key={component.component} className="mb-5">
            <h3 className="text-sm font-semibold text-slate-900">
              {component.component === "pollution_burden"
                ? "Pollution burden"
                : "Population characteristics"}
              <span className="ml-2 font-normal tabular-nums text-slate-500">
                {component.score.toFixed(1)} / 10
              </span>
            </h3>
          </section>
        ))}

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
                  <IndicatorRow key={i.id} indicator={i} />
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
                    className="text-slate-800 underline decoration-slate-300 hover:decoration-slate-800"
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
