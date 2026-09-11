/**
 * Citations as links, and a draft as text somebody can take away.
 *
 * Two jobs that share one constraint: **the reader must be able to check every
 * claim**, and a citation they cannot reach is a citation they will take on
 * trust. So every citation resolves to a public page, and the rendered text
 * carries the same references as the screen.
 *
 * There is no `send`, no `publish`, and no `shareToAgency` here, and there is
 * nowhere else in the frontend that has one. The only ways out of this
 * application are the clipboard and a downloaded file, both of which put a
 * person between the draft and whoever receives it. That is the design, not an
 * omission waiting to be filled in.
 */

import type { Citation, DraftDocument, GeneratedDraft, StatuteCitation } from "./types.ts";

/** Where a citation can be checked, or null when there is no public page. */
export function citationUrl(citation: Citation): string | null {
  if (citation.kind === "record") {
    // ECHO's facility report, keyed on the FRS registry id. The same page the
    // hexagon panel already links each facility to, so a reader following a
    // citation lands somewhere they recognise.
    return `https://echo.epa.gov/detailed-facility-report?fid=${encodeURIComponent(
      citation.record_id,
    )}`;
  }
  return statuteUrl(citation);
}

const USC = /^(\d+)\s*U\.?S\.?C\.?\s*§+\s*([0-9A-Za-z-]+)/;
const CFR = /^(\d+)\s*C\.?F\.?R\.?\s*§+\s*([0-9.]+)/;

/**
 * A statute section's page at a public publisher.
 *
 * Cornell's Legal Information Institute for the US Code and the eCFR for
 * regulations: both are stable, free, and show the section a reader is looking
 * for rather than a chapter they have to scroll. The corpus itself was built
 * from govinfo and the eCFR API, which serve documents rather than pages, so
 * the link is to where a person reads and not to where the ingestion fetched.
 *
 * Returns null rather than a guess for anything else, including case law. A
 * link that lands on the wrong page is worse than no link: the reader believes
 * they have checked.
 */
export function statuteUrl(citation: StatuteCitation): string | null {
  const usc = USC.exec(citation.section);
  if (usc) {
    return `https://www.law.cornell.edu/uscode/text/${usc[1]}/${usc[2]}`;
  }
  const cfr = CFR.exec(citation.section);
  if (cfr) {
    return `https://www.ecfr.gov/current/title-${cfr[1]}/section-${cfr[2]}`;
  }
  return null;
}

/** What a citation is called on screen. */
export function citationLabel(citation: Citation): string {
  return citation.kind === "statute" ? citation.section : citation.record_id;
}

const HEADINGS: Record<string, (d: DraftDocument) => string[]> = {
  public_comment_letter: (d) => [
    `To: ${d.recipient ?? ""}`,
    `Subject: ${d.subject ?? ""}`,
    ...(d.docket_reference ? [`Docket: ${d.docket_reference}`] : []),
  ],
  agency_complaint_draft: (d) => [
    `To: ${d.recipient_office ?? ""}`,
    "Administrative complaint",
  ],
  community_briefing_sheet: (d) => [d.headline ?? "", d.area_description ?? ""],
  journalist_fact_sheet: (d) => [d.headline ?? ""],
};

/**
 * The draft as plain text, for the clipboard and for a downloaded file.
 *
 * The notice goes first and the citations are listed at the end with their
 * URLs. A document that leaves this application and arrives somewhere without
 * its notice is the failure worth spending a few lines to prevent, and a
 * pasted draft with bare section numbers is one nobody will check.
 */
export function renderDraftText(stamped: GeneratedDraft): string {
  const d = stamped.document;
  const lines: string[] = [d.draft_notice, ""];

  const headings = HEADINGS[d.document_type]?.(d) ?? [];
  for (const heading of headings.filter(Boolean)) lines.push(heading);
  if (headings.some(Boolean)) lines.push("");

  if (d.what_this_means) lines.push(d.what_this_means, "");

  for (const paragraph of d.paragraphs) {
    const marks = paragraph.citations.map(citationLabel);
    lines.push(marks.length ? `${paragraph.text} [${marks.join("; ")}]` : paragraph.text, "");
  }

  if (d.key_figures?.length) {
    lines.push("Key figures", "");
    for (const figure of d.key_figures) {
      const unit = figure.unit ? ` ${figure.unit}` : "";
      lines.push(`- ${figure.label}: ${figure.value}${unit} [${citationLabel(figure.citation)}]`);
    }
    lines.push("");
  }

  if (d.what_you_can_do?.length) {
    lines.push("What you can do", "");
    for (const step of d.what_you_can_do) lines.push(`- ${step}`);
    lines.push("");
  }

  if (d.caveats?.length) {
    lines.push("Caveats", "");
    for (const caveat of d.caveats) lines.push(`- ${caveat}`);
    lines.push("");
  }

  if (d.requested_action) lines.push(d.requested_action, "");
  if (d.relief_sought) lines.push(`Relief sought: ${d.relief_sought}`, "");
  if (d.filing_note) lines.push(d.filing_note, "");

  lines.push("Citations", "");
  for (const citation of d.citations) {
    const url = citationUrl(citation);
    lines.push(`- ${citationLabel(citation)}${url ? ` — ${url}` : ""}`);
    lines.push(`  ${citation.proposition}`);
  }

  lines.push(
    "",
    "---",
    `Hexagon ${stamped.h3} · confidence ${stamped.confidence_band}`,
    `Methodology ${stamped.methodology_version} · corpus ${stamped.corpus_version} · prompt ${stamped.prompt_version}`,
    `Generated ${stamped.generated_at} by ${stamped.model}. Every citation was checked against the data and the statute corpus before this was shown.`,
  );

  return lines.join("\n");
}

/** A file name that says what it is and which hexagon it is about. */
export function draftFileName(stamped: GeneratedDraft): string {
  const day = stamped.generated_at.slice(0, 10);
  return `clearskies-draft-${stamped.document.document_type}-${stamped.h3}-${day}.txt`;
}
