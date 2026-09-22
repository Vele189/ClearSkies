import { useEffect, useState } from "react";

import { ApiError, getProvenance } from "../lib/api.ts";
import type { PullStatus, Provenance, SourcePull } from "../lib/types.ts";

/** Every source, when it was last pulled, and what it does not cover (CS-406).
 *
 *  Rendered from the live endpoint rather than from `docs/provenance.md`, so it
 *  cannot go stale. The Markdown file is the repository-side view of the same
 *  manifests; this is the reader's.
 */

const STATUS: Record<PullStatus, { label: string; className: string; meaning: string }> = {
  ok: {
    label: "Loaded",
    className: "bg-emerald-50 text-emerald-900 ring-emerald-200",
    meaning: "The last pull completed and every record it fetched was loaded.",
  },
  partial: {
    label: "Partial",
    className: "bg-amber-50 text-amber-900 ring-amber-200",
    meaning:
      "The last pull completed, and some records were rejected as malformed. " +
      "What loaded is sound; there is less of it than upstream published.",
  },
  stale: {
    label: "Served from a snapshot",
    className: "bg-amber-50 text-amber-900 ring-amber-200",
    meaning:
      "The source could not be reached, so the last good copy was used instead. " +
      "The data is real and it is older than the date below, and the confidence " +
      "value of every hexagon it feeds is reduced to say so.",
  },
  failed: {
    label: "Failed",
    className: "bg-rose-50 text-rose-900 ring-rose-200",
    meaning:
      "The last attempt did not load anything. Whatever this source feeds is as " +
      "old as the pull before it, or absent.",
  },
};

function when(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? iso
    : at.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function StatusTag({ status }: { status: PullStatus }) {
  const { label, className } = STATUS[status];
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${className}`}
    >
      {label}
    </span>
  );
}

function Source({ pull }: { pull: SourcePull }) {
  return (
    <article className="border-t border-slate-200 py-5">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-base font-semibold text-slate-900">{pull.title}</h3>
        <StatusTag status={pull.status} />
      </header>

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-slate-500">Release</dt>
        {/* The upstream release, not the download time. A 2019 assessment
            pulled last night is 2019 data, and reporting the pull date as the
            vintage would make the map look six years fresher than it is. */}
        <dd className="text-slate-900">{pull.vintage}</dd>

        <dt className="text-slate-500">Last pull</dt>
        <dd className="text-slate-900">{when(pull.pulled_at)}</dd>

        <dt className="text-slate-500">Records loaded</dt>
        <dd className="text-slate-900">
          {pull.records.toLocaleString()}
          {pull.rejected > 0 && (
            <span className="text-slate-500">
              {" "}
              · {pull.rejected.toLocaleString()} rejected as malformed
            </span>
          )}
        </dd>
      </dl>

      <p className="mt-3 text-sm text-slate-700">{STATUS[pull.status].meaning}</p>

      {pull.known_gaps.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-semibold text-slate-900">What this source does not cover</h4>
          <ul className="mt-1 space-y-1 text-sm text-slate-700">
            {pull.known_gaps.map((gap, index) => (
              <li key={index} className="flex gap-2">
                <span aria-hidden="true" className="text-slate-400">
                  •
                </span>
                <span>
                  {gap.detail}
                  {gap.affects.length > 0 && (
                    <span className="text-slate-500">
                      {" "}
                      Affects {gap.affects.join(", ")}.
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {pull.notes.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-slate-600">
          {pull.notes.map((note, index) => (
            <li key={index}>{note}</li>
          ))}
        </ul>
      )}

      {pull.artifacts.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm text-slate-600 hover:text-slate-900">
            Files downloaded ({pull.artifacts.length})
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-slate-600">
            {pull.artifacts.map((artifact) => (
              <li key={artifact.sha256} className="break-all">
                <span className="font-mono">{artifact.short_sha}</span>{" "}
                <a
                  href={artifact.url}
                  className="text-sky-800 underline focus-visible:outline-2
                             focus-visible:outline-offset-2 focus-visible:outline-sky-700"
                >
                  {artifact.url}
                </a>
                {artifact.from_snapshot && (
                  <span className="text-slate-500"> — served from a stored copy</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

export default function ProvenancePage() {
  const [data, setData] = useState<Provenance | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getProvenance(controller.signal)
      .then(setData)
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          err instanceof ApiError ? err.message : "Could not load the source records.",
        );
      });
    return () => controller.abort();
  }, []);

  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">Where the data comes from</h1>

      <p className="mt-3 text-sm text-slate-700">
        Every number on the map traces back to a public record. This page is generated
        from the pipeline's own manifests, so it says what actually happened on the last
        run rather than what is supposed to happen. Each source shows the upstream
        release it carries, when it was last fetched, and what it does not cover.
      </p>

      <h2 className="mt-8 text-base font-semibold text-slate-900">
        Two things worth knowing before reading the table
      </h2>

      <p className="mt-2 text-sm text-slate-700">
        <strong className="font-semibold">A missing value is never shown as a zero.</strong>{" "}
        They mean opposite things. Zero released is a measurement; no report filed is an
        absence. Where a value is missing the indicator is marked unavailable for that
        hexagon and left out of its score, and the hexagon's confidence value falls to
        record that less was known about it. A hexagon is never made to look clean by
        data that was never collected.
      </p>

      <p className="mt-3 text-sm text-slate-700">
        <strong className="font-semibold">Measured air quality is sparse.</strong> Louisiana
        has a few dozen air monitors for a state of 52,000 square miles, so most places
        are nowhere near one. That is why measured readings are a secondary input and
        modeled exposure is the primary one: the model covers everywhere evenly, and the
        monitors cover where the monitors are. A hexagon far from a monitor still gets a
        score, and its confidence value carries the distance.
      </p>

      <h2 className="mt-8 text-base font-semibold text-slate-900">Sources</h2>

      {error !== null && (
        <p role="status" className="mt-3 text-sm text-slate-700">
          {error}
        </p>
      )}

      {error === null && data === null && (
        <p role="status" className="mt-3 text-sm text-slate-500">
          Loading the source records…
        </p>
      )}

      {data !== null && data.sources.length === 0 && (
        <p className="mt-3 text-sm text-slate-700">
          No source has been pulled into this deployment yet, so there is nothing to
          report. An empty table here means the pipeline has not run, not that the
          sources are empty.
        </p>
      )}

      {data?.sources.map((pull) => <Source key={pull.source} pull={pull} />)}
    </div>
  );
}
