/**
 * Draft a document about one hexagon.
 *
 * Three things about this component are safety properties rather than design
 * choices, and all three should survive any redesign of how it looks.
 *
 * **The draft framing is impossible to miss.** The notice is the first thing in
 * the document, in a banner that does not scroll away, and it is repeated in
 * anything copied or downloaded. A document that leaves here and arrives
 * somewhere without it is the failure the banner exists to prevent, and people
 * paste rather than screenshot.
 *
 * **Every citation is a link.** A citation a reader cannot follow is one they
 * take on trust, which is the opposite of the point. Where a public page exists
 * the reference is an anchor; where one does not, it is plain text rather than
 * a guessed URL, because a link that lands on the wrong page is worse than no
 * link at all.
 *
 * **There is no send button.** Copy and download, and nothing else. Both put a
 * person between the draft and whoever receives it, which is the whole
 * argument: this tool produces a first draft for somebody to check, and a
 * system that could file one directly would be a system that files unchecked
 * legal documents.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils.ts";
import { Button } from "./ui/button.tsx";

import { ApiError, postDraft } from "../lib/api.ts";
import {
  allCitations,
  citationLabel,
  citationUrl,
  distinctByLabel,
  draftFileName,
  renderDraftText,
} from "../lib/draft.ts";
import {
  DOCUMENT_TYPE_BLURBS,
  DOCUMENT_TYPE_LABELS,
  type Citation,
  type DocumentType,
  type DraftDocument,
  type GeneratedDraft,
  type HexDetail,
  type Refusal,
} from "../lib/types.ts";

const TYPES: DocumentType[] = [
  "public_comment_letter",
  "agency_complaint_draft",
  "community_briefing_sheet",
  "journalist_fact_sheet",
];

type Status =
  | { kind: "idle" }
  | { kind: "generating"; documentType: DocumentType }
  | { kind: "drafted"; draft: GeneratedDraft; fromCache: boolean }
  | { kind: "refused"; refusal: Refusal }
  | { kind: "failed"; status: number; detail: string };

function CitationLink({ citation }: { citation: Citation }) {
  const href = citationUrl(citation);
  const label = citationLabel(citation);

  if (href === null) {
    return (
      <span
        className="rounded bg-secondary px-1 font-mono text-[0.6875rem] text-body"
        title={citation.proposition}
      >
        {label}
      </span>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      title={citation.proposition}
      className="rounded bg-citation-surface px-1 font-mono text-[0.6875rem] text-link
                 underline decoration-dotted underline-offset-2 hover:no-underline"
    >
      {label}
    </a>
  );
}

function Paragraphs({ document }: { document: DraftDocument }) {
  return (
    <>
      {document.paragraphs.map((paragraph, i) => (
        <p key={i} className="mb-3.5 text-sm leading-relaxed text-body">
          {paragraph.text}
          {paragraph.citations.length > 0 && (
            <span className="ml-1.5 inline-flex flex-wrap gap-1 align-baseline">
              {distinctByLabel(paragraph.citations).map((citation, j) => (
                <CitationLink key={j} citation={citation} />
              ))}
            </span>
          )}
        </p>
      ))}
    </>
  );
}

function Heading({ document }: { document: DraftDocument }) {
  const rows: [string, string][] = [];
  if (document.recipient) rows.push(["To", document.recipient]);
  if (document.recipient_office) rows.push(["To", document.recipient_office]);
  if (document.subject) rows.push(["Subject", document.subject]);
  if (document.docket_reference) rows.push(["Docket", document.docket_reference]);

  if (rows.length === 0 && !document.headline) return null;

  return (
    <div className="mb-4">
      {document.headline && (
        <h3 className="mb-1 text-base leading-snug font-semibold">{document.headline}</h3>
      )}
      {document.area_description && (
        <p className="mb-2 text-sm text-muted-foreground">{document.area_description}</p>
      )}
      {rows.map(([label, value]) => (
        <p key={label} className="text-sm text-body">
          <span className="text-faint">{label}: </span>
          {value}
        </p>
      ))}
    </div>
  );
}

function Extras({ document }: { document: DraftDocument }) {
  return (
    <>
      {document.what_this_means && (
        <section className="mb-4 rounded-md border border-border bg-sunken p-3.5">
          <h4 className="mb-1.5 text-[0.6875rem] font-semibold tracking-[0.06em] text-muted-foreground uppercase">
            What this means
          </h4>
          <p className="text-sm text-body">{document.what_this_means}</p>
        </section>
      )}

      {document.key_figures && document.key_figures.length > 0 && (
        <section className="mb-4">
          <h4 className="mb-1.5 text-[0.6875rem] font-semibold tracking-[0.06em] text-muted-foreground uppercase">
            Key facts
          </h4>
          <ul className="space-y-1">
            {document.key_figures.map((figure, i) => (
              <li key={i} className="text-sm text-body">
                <span className="text-faint">{figure.label}: </span>
                <span className="font-medium">
                  {figure.value}
                  {figure.unit ? ` ${figure.unit}` : ""}
                </span>{" "}
                <CitationLink citation={figure.citation} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* The authority a complaint rests on. It is what makes the document an
          administrative complaint rather than a letter of concern, so it is on
          the page and in anything copied or downloaded. */}
      {document.legal_basis && document.legal_basis.length > 0 && (
        <section className="mb-4">
          <h4 className="mb-1.5 text-[0.6875rem] font-semibold tracking-[0.06em] text-muted-foreground uppercase">
            Laws this relies on
          </h4>
          <ul className="space-y-1">
            {document.legal_basis.map((citation, i) => (
              <li key={i} className="text-sm text-body">
                <CitationLink citation={citation} />
                <span className="ml-1 text-muted-foreground">{citation.proposition}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {document.what_you_can_do && document.what_you_can_do.length > 0 && (
        <section className="mb-4">
          <h4 className="mb-1.5 text-[0.6875rem] font-semibold tracking-[0.06em] text-muted-foreground uppercase">
            What you can do
          </h4>
          <ul className="list-disc space-y-1 pl-5">
            {document.what_you_can_do.map((step, i) => (
              <li key={i} className="text-sm text-body">
                {step}
              </li>
            ))}
          </ul>
        </section>
      )}

      {document.requested_action && (
        <p className="mb-4 text-sm font-medium text-foreground">{document.requested_action}</p>
      )}

      {document.relief_sought && (
        <p className="mb-4 text-sm text-body">
          <span className="text-faint">What is being asked for: </span>
          {document.relief_sought}
        </p>
      )}

      {/* The complaint says on its face that it is not a lawsuit. Sandoval is in
          the corpus for this reason, and a reader who takes a complaint to a
          court has been sent somewhere that will not hear it. */}
      {document.filing_note && (
        <p className="mb-4 rounded-md border border-warn-border bg-warn-surface p-2.5 text-xs leading-relaxed text-warn-foreground">
          {document.filing_note}
        </p>
      )}

      {document.caveats && document.caveats.length > 0 && (
        <section className="mb-4 rounded-md border border-warn-border bg-warn-surface p-3.5">
          <h4 className="mb-1.5 text-[0.6875rem] font-semibold tracking-[0.06em] text-warn-foreground uppercase">
            Things to keep in mind
          </h4>
          <ul className="list-disc space-y-1 pl-5">
            {document.caveats.map((caveat, i) => (
              <li key={i} className="text-xs leading-relaxed text-warn-foreground">
                {caveat}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

/** How long a downloaded draft's blob URL is kept alive. Revoking it in the
 *  same tick as the click races the download the click started, and a browser
 *  that has not fetched it yet saves nothing. A minute is far longer than any
 *  of them need and the page is not holding much: one short text file. */
const BLOB_LIFETIME_MS = 60_000;

function DraftView({ stamped, fromCache }: { stamped: GeneratedDraft; fromCache: boolean }) {
  const [copied, setCopied] = useState<"yes" | "no" | "failed">("no");
  const document_ = stamped.document;
  const citations = allCitations(document_);

  const copy = useCallback(() => {
    // A clipboard write can be refused — no permission, or no clipboard at all
    // over plain HTTP. Saying so is the point: a reader who believes they have
    // the draft and pastes nothing has lost it.
    navigator.clipboard.writeText(renderDraftText(stamped, window.location.origin)).then(
      () => {
        setCopied("yes");
        window.setTimeout(() => setCopied("no"), 2000);
      },
      () => setCopied("failed"),
    );
  }, [stamped]);

  const download = useCallback(() => {
    const blob = new Blob([renderDraftText(stamped, window.location.origin)], {
      type: "text/plain;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = draftFileName(stamped);
    anchor.click();
    window.setTimeout(() => {
      URL.revokeObjectURL(url);
    }, BLOB_LIFETIME_MS);
  }, [stamped]);

  return (
    <div>
      <h4 className="mb-3 text-base font-semibold text-foreground">
        {DOCUMENT_TYPE_LABELS[document_.document_type]}
        <span className="ml-2 text-xs font-normal text-muted-foreground">draft</span>
      </h4>

      {/* Not dismissible, and first. People paste rather than screenshot, so
          renderDraftText repeats it at the top of anything that leaves here. */}
      <div
        role="note"
        className="mb-4 rounded-md border-2 border-warn-border-strong bg-warn-surface p-3.5
                   text-xs leading-relaxed text-warn-foreground"
      >
        <span className="font-bold tracking-[0.04em] uppercase">Draft for human review. </span>
        {document_.draft_notice.replace("DRAFT FOR HUMAN REVIEW. ", "")}
      </div>

      <Heading document={document_} />
      <Extras document={document_} />
      <Paragraphs document={document_} />

      <section className="mt-6 border-t border-border pt-3.5">
        <h4 className="mb-2 text-[0.6875rem] font-semibold tracking-[0.06em] text-muted-foreground uppercase">
          Sources ({citations.length})
        </h4>
        <p className="mb-2.5 text-xs leading-relaxed text-faint">
          We checked every one against the EPA data and the text of the law before showing you
          this draft. Click any of them to check for yourself.
        </p>
        <ul className="space-y-2">
          {citations.map((citation, i) => (
            <li key={i} className="text-xs">
              <CitationLink citation={citation} />
              <span className="ml-1 text-muted-foreground">{citation.proposition}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Copy and download. There is no send, publish or share-to-agency
          control here or anywhere else in this application. */}
      {/* Pinned to the bottom of the scrolling panel while the draft is on
          screen, so taking it away does not mean scrolling past every
          paragraph to find out how. */}
      <div className="sticky bottom-0 -mx-5 mt-6 flex flex-wrap items-center gap-2 border-t border-border bg-sunken/95 px-5 py-3 backdrop-blur-sm">
        <Button size="sm" onClick={copy}>
          {copied === "yes" ? "Copied" : "Copy"}
        </Button>
        <Button variant="outline" size="sm" onClick={download}>
          Download
        </Button>
        <span className="text-xs text-faint">
          Saved as plain text, with the draft warning and every source.
        </span>
      </div>

      {copied === "failed" && (
        <p
          role="status"
          className="mt-2.5 rounded border border-warn-border bg-warn-surface px-2.5 py-1.5
                     text-xs leading-relaxed text-warn-foreground"
        >
          Your browser didn&apos;t allow copying. Select the text above and copy it yourself, or
          use Download.
        </p>
      )}

      {/* For anyone checking or reproducing the draft later; not something a
          reader needs, so it is labelled as what it is and kept small. */}
      <p className="mt-4 text-[0.6875rem] leading-relaxed text-faint">
        Technical details: area {stamped.h3} · data {stamped.confidence_band} · method{" "}
        {stamped.methodology_version} · corpus {stamped.corpus_version} · prompt{" "}
        {stamped.prompt_version} · {stamped.model}
        {fromCache && " · served from cache"}
      </p>
    </div>
  );
}

function Refused({ refusal }: { refusal: Refusal }) {
  return (
    <div role="status" className="rounded-md border border-border-strong bg-sunken p-4">
      <h4 className="mb-1.5 text-sm font-semibold">
        The assistant didn&apos;t write this one
      </h4>
      <p className="text-sm leading-relaxed text-body">{refusal.explanation}</p>
      {refusal.missing.length > 0 && (
        <>
          <p className="mt-2.5 text-xs text-faint">What was missing:</p>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {refusal.missing.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </>
      )}
      <p className="mt-3.5 text-xs leading-relaxed text-faint">
        This is the assistant declining rather than failing. It only writes what it can back up
        with this area&apos;s data and the set of laws it has, and it couldn&apos;t back this up,
        so it stopped rather than guess.
      </p>
    </div>
  );
}

function Failed({ status, detail }: { status: number; detail: string }) {
  // The API writes this sentence knowing which of six things went wrong. The
  // frontend does not, so it renders the detail rather than inventing wording
  // from the status code.
  const tone =
    status === 409
      ? "border-border-strong bg-sunken text-body"
      : "border-warn-border bg-warn-surface text-warn-foreground";

  return (
    <div role="status" className={cn("rounded-md border p-4 text-sm leading-relaxed", tone)}>
      <p>{detail}</p>
    </div>
  );
}

export default function DraftPanel({ hex }: { hex: HexDetail }) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  /** The type last asked for, so a refusal or failure still shows which. */
  const [lastType, setLastType] = useState<DocumentType | null>(null);
  const pending = useRef<AbortController | null>(null);

  const insufficient = hex.confidence.band === "insufficient";
  const chosenType: DocumentType | null =
    status.kind === "generating"
      ? status.documentType
      : status.kind === "drafted"
        ? status.draft.document.document_type
        : status.kind === "refused" || status.kind === "failed"
          ? lastType
          : null;

  // A draft in flight belongs to the hexagon it was asked about. If the reader
  // moves on before it lands, it is abandoned rather than shown under a heading
  // for a different place. The parent keys this panel on the hexagon, so the
  // state resets with it; this makes sure nothing late arrives into the reset.
  useEffect(
    () => () => {
      pending.current?.abort();
      pending.current = null;
    },
    [hex.h3],
  );

  const generate = useCallback(
    (documentType: DocumentType) => {
      pending.current?.abort();
      const controller = new AbortController();
      pending.current = controller;

      setLastType(documentType);
      setStatus({ kind: "generating", documentType });
      postDraft(hex.h3, documentType, controller.signal)
        .then((response) => {
          if (controller.signal.aborted) return;
          if (response.status === "refused" && response.refusal) {
            setStatus({ kind: "refused", refusal: response.refusal });
          } else if (response.draft) {
            setStatus({ kind: "drafted", draft: response.draft, fromCache: response.from_cache });
          } else {
            setStatus({
              kind: "failed",
              status: 0,
              detail: "No draft came back. Please try again.",
            });
          }
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          setStatus({
            kind: "failed",
            status: error instanceof ApiError ? error.status : 0,
            detail:
              error instanceof ApiError
                ? error.message
                : "Could not reach our service. Check your connection and try again.",
          });
        });
    },
    [hex.h3],
  );

  return (
    <section className="border-t border-border bg-sunken px-5 py-5">
      <h3 className="text-sm font-semibold">Draft a document</h3>
      <p className="mt-1 mb-3.5 text-xs leading-relaxed text-muted-foreground">
        Get a first draft to check and edit, written from this area&apos;s data and a fixed set
        of environmental laws. Nothing leaves this page unless you copy or download it.
      </p>

      {/* The refusal is explained before anything is clicked, in plain language.
          The reader is being told the tool does not trust its own number for
          their neighbourhood, which deserves a sentence rather than a disabled
          button with no reason on it. */}
      {hex.score === null ? (
        // Unscored is not the same as poorly scored: there is no number here to
        // be unsure of, so the insufficient-band wording below would be wrong.
        <div role="status" className="rounded-md border border-border-strong bg-card p-3.5">
          <p className="text-sm leading-relaxed text-body">
            This area isn&apos;t ranked, so there&apos;s nothing here to base a document on.
          </p>
          <p className="mt-2.5 text-xs leading-relaxed text-faint">
            Pick a coloured area nearby on the map. Most places where people live are ranked.
          </p>
        </div>
      ) : insufficient ? (
        <div role="status" className="rounded-md border border-border-strong bg-card p-3.5">
          <p className="text-sm leading-relaxed text-body">
            We don&apos;t have enough data about this area to stand behind a document based on
            it. A draft would look well supported when it isn&apos;t.
          </p>
          <p className="mt-2.5 text-xs leading-relaxed text-faint">
            &ldquo;How sure we are&rdquo; above shows what&apos;s missing. Nearby areas with
            better data can be used instead.
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            {TYPES.map((documentType) => {
              const busy = status.kind === "generating";
              const thisOne = status.kind === "generating" && status.documentType === documentType;
              // Which document is on screen below, so a reader who scrolls back
              // up can see what they asked for and that the others are a click
              // away rather than a reset.
              const chosen = chosenType === documentType;
              return (
                <button
                  key={documentType}
                  onClick={() => generate(documentType)}
                  disabled={busy}
                  aria-busy={thisOne}
                  aria-pressed={chosen}
                  className={cn(
                    "rounded-md border bg-card p-2.5 text-left transition-colors",
                    "hover:border-foreground disabled:cursor-wait disabled:opacity-60",
                    chosen || thisOne
                      ? "border-foreground ring-1 ring-foreground"
                      : "border-input",
                  )}
                >
                  <span className="block text-sm font-medium text-foreground">
                    {DOCUMENT_TYPE_LABELS[documentType]}
                  </span>
                  <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">
                    {thisOne ? "Writing, then checking every source…" : DOCUMENT_TYPE_BLURBS[documentType]}
                  </span>
                </button>
              );
            })}
          </div>

          {status.kind === "generating" && (
            <p role="status" className="mt-3.5 text-xs leading-relaxed text-faint">
              This takes a few seconds. We check every fact and every law the draft relies on
              before showing it to you.
            </p>
          )}

          <div className="mt-4">
            {status.kind === "drafted" && (
              <DraftView stamped={status.draft} fromCache={status.fromCache} />
            )}
            {status.kind === "refused" && <Refused refusal={status.refusal} />}
            {status.kind === "failed" && (
              <Failed status={status.status} detail={status.detail} />
            )}
          </div>
        </>
      )}
    </section>
  );
}
