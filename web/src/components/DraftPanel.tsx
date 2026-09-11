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

import { useCallback, useState } from "react";

import { ApiError, postDraft } from "../lib/api.ts";
import { citationLabel, citationUrl, draftFileName, renderDraftText } from "../lib/draft.ts";
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
      <span className="rounded bg-slate-100 px-1 font-mono text-xs text-slate-700" title={citation.proposition}>
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
      className="rounded bg-sky-50 px-1 font-mono text-xs text-sky-800 underline decoration-dotted hover:bg-sky-100"
    >
      {label}
    </a>
  );
}

function Paragraphs({ document }: { document: DraftDocument }) {
  return (
    <>
      {document.paragraphs.map((paragraph, i) => (
        <p key={i} className="mb-3 text-sm leading-relaxed text-slate-800">
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
        <h3 className="mb-1 text-base font-semibold text-slate-900">{document.headline}</h3>
      )}
      {document.area_description && (
        <p className="mb-2 text-sm text-slate-600">{document.area_description}</p>
      )}
      {rows.map(([label, value]) => (
        <p key={label} className="text-sm text-slate-700">
          <span className="text-slate-500">{label}: </span>
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
        <section className="mb-4 rounded border border-slate-200 bg-slate-50 p-3">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            What this means
          </h4>
          <p className="text-sm text-slate-800">{document.what_this_means}</p>
        </section>
      )}

      {document.key_figures && document.key_figures.length > 0 && (
        <section className="mb-4">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Key figures
          </h4>
          <ul className="space-y-1">
            {document.key_figures.map((figure, i) => (
              <li key={i} className="text-sm text-slate-800">
                <span className="text-slate-500">{figure.label}: </span>
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

      {document.what_you_can_do && document.what_you_can_do.length > 0 && (
        <section className="mb-4">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            What you can do
          </h4>
          <ul className="list-disc space-y-1 pl-5">
            {document.what_you_can_do.map((step, i) => (
              <li key={i} className="text-sm text-slate-800">
                {step}
              </li>
            ))}
          </ul>
        </section>
      )}

      {document.requested_action && (
        <p className="mb-4 text-sm font-medium text-slate-900">{document.requested_action}</p>
      )}

      {document.relief_sought && (
        <p className="mb-4 text-sm text-slate-800">
          <span className="text-slate-500">Relief sought: </span>
          {document.relief_sought}
        </p>
      )}

      {/* The complaint says on its face that it is not a lawsuit. Sandoval is in
          the corpus for this reason, and a reader who takes a complaint to a
          court has been sent somewhere that will not hear it. */}
      {document.filing_note && (
        <p className="mb-4 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
          {document.filing_note}
        </p>
      )}

      {document.caveats && document.caveats.length > 0 && (
        <section className="mb-4 rounded border border-amber-200 bg-amber-50 p-3">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-800">
            Caveats
          </h4>
          <ul className="list-disc space-y-1 pl-5">
            {document.caveats.map((caveat, i) => (
              <li key={i} className="text-xs text-amber-900">
                {caveat}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function DraftView({ stamped, fromCache }: { stamped: GeneratedDraft; fromCache: boolean }) {
  const [copied, setCopied] = useState(false);
  const document_ = stamped.document;

  const copy = useCallback(() => {
    void navigator.clipboard.writeText(renderDraftText(stamped)).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  }, [stamped]);

  const download = useCallback(() => {
    const blob = new Blob([renderDraftText(stamped)], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = draftFileName(stamped);
    anchor.click();
    URL.revokeObjectURL(url);
  }, [stamped]);

  return (
    <div>
      {/* Not dismissible, and first. People paste rather than screenshot, so
          renderDraftText repeats it at the top of anything that leaves here. */}
      <div
        role="note"
        className="mb-4 rounded border-2 border-amber-400 bg-amber-50 p-3 text-xs leading-relaxed text-amber-950"
      >
        <span className="font-bold uppercase tracking-wide">Draft for human review. </span>
        {document_.draft_notice.replace("DRAFT FOR HUMAN REVIEW. ", "")}
      </div>

      <Heading document={document_} />
      <Extras document={document_} />
      <Paragraphs document={document_} />

      <section className="mt-5 border-t border-slate-200 pt-3">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Citations ({document_.citations.length})
        </h4>
        <p className="mb-2 text-xs text-slate-500">
          Every one was checked against the EPA data and the statute corpus before this was
          shown. Follow them.
        </p>
        <ul className="space-y-2">
          {document_.citations.map((citation, i) => (
            <li key={i} className="text-xs">
              <CitationLink citation={citation} />
              <span className="ml-1 text-slate-600">{citation.proposition}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Copy and download. There is no send, publish or share-to-agency
          control here or anywhere else in this application. */}
      <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-200 pt-3">
        <button
          onClick={copy}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <button
          onClick={download}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
        >
          Download
        </button>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-slate-400">
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
    <div role="status" className="rounded border border-slate-300 bg-slate-50 p-4">
      <h4 className="mb-1 text-sm font-semibold text-slate-900">
        No draft was written for this
      </h4>
      <p className="text-sm text-slate-700">{refusal.explanation}</p>
      {refusal.missing.length > 0 && (
        <>
          <p className="mt-2 text-xs text-slate-500">What was missing:</p>
          <ul className="list-disc pl-5 text-xs text-slate-600">
            {refusal.missing.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </>
      )}
      <p className="mt-3 text-xs text-slate-500">
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
      ? "border-slate-300 bg-slate-50 text-slate-700"
      : "border-amber-300 bg-amber-50 text-amber-900";

  return (
    <div role="status" className={`rounded border p-4 text-sm ${tone}`}>
      <p>{detail}</p>
    </div>
  );
}

export default function DraftPanel({ hex }: { hex: HexDetail }) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const insufficient = hex.confidence.band === "insufficient";

  const generate = useCallback(
    (documentType: DocumentType) => {
      setStatus({ kind: "generating", documentType });
      postDraft(hex.h3, documentType)
        .then((response) => {
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
    <section className="border-t border-slate-200 px-5 py-4">
      <h3 className="mb-1 text-sm font-semibold text-slate-900">Draft a document</h3>
      <p className="mb-3 text-xs leading-relaxed text-slate-500">
        A first draft for you to check and rewrite, built from this hexagon&apos;s data and a
        fixed corpus of statutes. Never sent anywhere.
      </p>

      {/* The refusal is explained before anything is clicked, in plain language.
          The reader is being told the tool does not trust its own number for
          their neighbourhood, which deserves a sentence rather than a disabled
          button with no reason on it. */}
      {insufficient ? (
        <div role="status" className="rounded border border-slate-300 bg-slate-50 p-3">
          <p className="text-sm text-slate-700">
            There is not enough data behind this hexagon&apos;s score to stand behind a document
            built on it. Drafting from it would give you something that looks well supported and
            is not.
          </p>
          <p className="mt-2 text-xs text-slate-500">
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
                  className="rounded border border-slate-300 p-2 text-left hover:bg-slate-50 disabled:cursor-wait disabled:opacity-60"
                >
                  <span className="block text-sm font-medium text-slate-800">
                    {DOCUMENT_TYPE_LABELS[documentType]}
                  </span>
                  <span className="block text-xs text-slate-500">
                    {thisOne ? "Writing and checking every citation…" : DOCUMENT_TYPE_BLURBS[documentType]}
                  </span>
                </button>
              );
            })}
          </div>

          {status.kind === "generating" && (
            <p role="status" className="mt-3 text-xs text-slate-500">
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
