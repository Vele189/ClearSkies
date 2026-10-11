import { useEffect, useState } from "react";

import { ExternalLink } from "../components/Link.tsx";
import { Mono, PageTitle, Point, Prose, Section } from "../components/Prose.tsx";
import { Badge } from "../components/ui/badge.tsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.tsx";
import { Separator } from "../components/ui/separator.tsx";
import { Skeleton } from "../components/ui/skeleton.tsx";
import { ApiError, getProvenance } from "../lib/api.ts";
import type { PullStatus, Provenance, SourcePull } from "../lib/types.ts";

/** Every source, when it was last pulled, and what it does not cover (CS-406).
 *
 *  Rendered from the live endpoint rather than from `docs/provenance.md`, so it
 *  cannot go stale. The Markdown file is the repository-side view of the same
 *  manifests; this is the reader's.
 */

/** The badge variant per state, and the sentence that says what the state
 *  means. The variant carries no information on its own: every badge prints
 *  its status in words, because a reader who cannot separate amber from rose
 *  still has to be able to tell "Partial" from "Failed". */
const STATUS: Record<
  PullStatus,
  { label: string; variant: "ok" | "warn" | "bad"; meaning: string }
> = {
  ok: {
    label: "Loaded",
    variant: "ok",
    meaning: "The last pull completed and every record it fetched was loaded.",
  },
  partial: {
    label: "Partial",
    variant: "warn",
    meaning:
      "The last pull completed, and some records were rejected as malformed. " +
      "What loaded is sound; there is less of it than upstream published.",
  },
  stale: {
    label: "Served from a snapshot",
    variant: "warn",
    meaning:
      "The source could not be reached, so the last good copy was used instead. " +
      "The data is real and it is older than the date below, and the confidence " +
      "value of every hexagon it feeds is reduced to say so.",
  },
  failed: {
    label: "Failed",
    variant: "bad",
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

/** One labelled figure in the source's summary row. */
function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[0.6875rem] font-semibold tracking-[0.06em] text-faint uppercase">
        {term}
      </dt>
      <dd className="mt-1 text-sm text-foreground">{children}</dd>
    </div>
  );
}

function Source({ pull }: { pull: SourcePull }) {
  const status = STATUS[pull.status];
  return (
    <Card className="mt-5">
      <CardHeader className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <CardTitle>{pull.title}</CardTitle>
        <Badge variant={status.variant}>{status.label}</Badge>
      </CardHeader>

      <CardContent className="pt-4">
        <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-3">
          {/* The upstream release, not the download time. A 2019 assessment
              pulled last night is 2019 data, and reporting the pull date as the
              vintage would make the map look six years fresher than it is. */}
          <Fact term="Release">{pull.vintage}</Fact>
          <Fact term="Last pull">{when(pull.pulled_at)}</Fact>
          <Fact term="Records loaded">
            {pull.records.toLocaleString()}
            {pull.rejected > 0 && (
              <span className="block text-xs text-muted-foreground">
                {pull.rejected.toLocaleString()} rejected as malformed
              </span>
            )}
          </Fact>
        </dl>

        <Separator className="my-4" />

        <p className="text-sm leading-relaxed text-body">{status.meaning}</p>

        {pull.known_gaps.length > 0 && (
          <div className="mt-5 rounded-md border border-border bg-sunken px-4 py-3.5">
            <h4 className="text-sm font-semibold">What this source does not cover</h4>
            <ul className="mt-2 space-y-1.5 text-sm leading-relaxed text-body">
              {pull.known_gaps.map((gap, index) => (
                <li key={index} className="flex gap-2.5">
                  <span aria-hidden="true" className="text-border-strong select-none">
                    —
                  </span>
                  <span>
                    {gap.detail}
                    {gap.affects.length > 0 && (
                      <span className="text-muted-foreground">
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
          <ul className="mt-4 space-y-1 text-sm leading-relaxed text-muted-foreground">
            {pull.notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        )}

        {pull.artifacts.length > 0 && (
          <details className="group mt-4">
            <summary className="w-fit cursor-pointer rounded text-sm font-medium text-muted-foreground hover:text-foreground">
              Files downloaded ({pull.artifacts.length})
            </summary>
            <ul className="mt-2.5 space-y-1.5 text-xs text-muted-foreground">
              {pull.artifacts.map((artifact) => (
                <li key={artifact.sha256} className="break-all">
                  <Mono className="text-faint">{artifact.short_sha}</Mono>{" "}
                  <ExternalLink href={artifact.url}>{artifact.url}</ExternalLink>
                  {artifact.from_snapshot && (
                    <span className="text-faint"> — served from a stored copy</span>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
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
      <PageTitle
        lede="Every number on the map traces back to a public record. This page is generated
              from the pipeline's own manifests, so it says what actually happened on the
              last run rather than what is supposed to happen."
      >
        Where the data comes from
      </PageTitle>

      <Prose>
        <p>
          Each source below shows the upstream release it carries, when it was last
          fetched, and what it does not cover.
        </p>
      </Prose>

      <Section title="Two things worth knowing before reading the table">
        <Point label="A missing value is never shown as a zero.">
          They mean opposite things. Zero released is a measurement; no report filed is an
          absence. Where a value is missing the indicator is marked unavailable for that
          hexagon and left out of its score, and the hexagon's confidence value falls to
          record that less was known about it. A hexagon is never made to look clean by
          data that was never collected.
        </Point>
        <Point label="Measured air quality is sparse.">
          Louisiana has a few dozen air monitors for a state of 52,000 square miles, so
          most places are nowhere near one. That is why measured readings are a secondary
          input and modeled exposure is the primary one: the model covers everywhere
          evenly, and the monitors cover where the monitors are. A hexagon far from a
          monitor still gets a score, and its confidence value carries the distance.
        </Point>
      </Section>

      <section className="mt-10">
        <h2 className="text-xl font-semibold">Sources</h2>

        {error !== null && (
          <p role="status" className="mt-3 text-sm text-body">
            {error}
          </p>
        )}

        {error === null && data === null && (
          <div className="mt-3">
            <p role="status" className="text-sm text-muted-foreground">
              Loading the source records…
            </p>
            <div className="mt-4 space-y-3">
              <Skeleton className="h-28 w-full rounded-lg" />
              <Skeleton className="h-28 w-full rounded-lg" />
            </div>
          </div>
        )}

        {data !== null && data.sources.length === 0 && (
          <p className="measure mt-3 font-serif text-[1.0625rem] leading-[1.7] text-body">
            No source has been pulled into this deployment yet, so there is nothing to
            report. An empty table here means the pipeline has not run, not that the
            sources are empty.
          </p>
        )}

        {data?.sources.map((pull) => <Source key={pull.source} pull={pull} />)}
      </section>
    </div>
  );
}
