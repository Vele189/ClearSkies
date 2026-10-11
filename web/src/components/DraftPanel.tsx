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
              {paragraph.citations.map((citation, j) => (
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
            Key figures
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
            Legal basis
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
          <span className="text-faint">Relief sought: </span>
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
            Caveats
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
    navigator.clipboard.writeText(renderDraftText(stamped)).then(
      () => {
        setCopied("yes");
        window.setTimeout(() => setCopied("no"), 2000);
      },
      () => setCopied("failed"),
    );
  }, [stamped]);

  const download = useCallback(() => {
    const blob = new Blob([renderDraftText(stamped)], { type: "text/plain;charset=utf-8" });
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
          Citations ({citations.length})
        </h4>
        <p className="mb-2.5 text-xs leading-relaxed text-faint">
          Every one was checked against the EPA data and the statute corpus before this was
          shown. Follow them.
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
      <div className="mt-6 flex flex-wrap gap-2 border-t border-border pt-3.5">
        <Button variant="outline" size="sm" onClick={copy}>
          {copied === "yes" ? "Copied" : "Copy"}
        </Button>
        <Button variant="outline" size="sm" onClick={download}>
          Download
        </Button>
      </div>

      {copied === "failed" && (
        <p
          role="status"
          className="mt-2.5 rounded border border-warn-border bg-warn-surface px-2.5 py-1.5
                     text-xs leading-relaxed text-warn-foreground"
        >
          The browser would not let the page write to the clipboard. Select the draft above and
          copy it yourself, or use Download.
        </p>
      )}

      <p className="mt-4 text-[0.6875rem] leading-relaxed text-faint">
        Hexagon {stamped.h3} · confidence {stamped.confidence_band} · methodology{" "}
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
        No draft was written for this
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
        This is the assistant declining rather than failing. It writes from a fixed set of
        statutes and this hexagon&apos;s data, and will not write a document it cannot support
        from them.
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
  const pending = useRef<AbortController | null>(null);

  const insufficient = hex.confidence.band === "insufficient";

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
              detail: "The API returned neither a draft nor a refusal.",
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
                : "Could not reach the API. Check your connection and try again.",
          });
        });
    },
    [hex.h3],
  );

  return (
    <section className="border-t border-border bg-sunken px-5 py-5">
      <h3 className="text-sm font-semibold">Draft a document</h3>
      <p className="mt-1 mb-3.5 text-xs leading-relaxed text-muted-foreground">
        A first draft for you to check and rewrite, built from this hexagon&apos;s data and a
        fixed corpus of statutes. Never sent anywhere.
      </p>

      {/* The refusal is explained before anything is clicked, in plain language.
          The reader is being told the tool does not trust its own number for
          their neighbourhood, which deserves a sentence rather than a disabled
          button with no reason on it. */}
      {insufficient ? (
        <div role="status" className="rounded-md border border-border-strong bg-card p-3.5">
          <p className="text-sm leading-relaxed text-body">
            There is not enough data behind this hexagon&apos;s score to stand behind a document
            built on it. Drafting from it would give you something that looks well supported and
            is not.
          </p>
          <p className="mt-2.5 text-xs leading-relaxed text-faint">
            The confidence breakdown above shows which inputs are missing. Nearby hexagons with
            better coverage can be drafted from.
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            {TYPES.map((documentType) => {
              const busy = status.kind === "generating";
              const thisOne = status.kind === "generating" && status.documentType === documentType;
              return (
                <button
                  key={documentType}
                  onClick={() => generate(documentType)}
                  disabled={busy}
                  aria-busy={thisOne}
                  className="rounded-md border border-input bg-card p-2.5 text-left
                             transition-colors hover:border-foreground disabled:cursor-wait
                             disabled:opacity-60"
                >
                  <span className="block text-sm font-medium text-foreground">
                    {DOCUMENT_TYPE_LABELS[documentType]}
                  </span>
                  <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">
                    {thisOne ? "Writing and checking every citation…" : DOCUMENT_TYPE_BLURBS[documentType]}
                  </span>
                </button>
              );
            })}
          </div>

          {status.kind === "generating" && (
            <p role="status" className="mt-3.5 text-xs leading-relaxed text-faint">
              This takes a few seconds. The draft is written, then every citation in it is
              checked against the data and the statute corpus before you see it.
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
