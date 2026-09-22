import { describe, expect, it } from "vitest";

import {
  allCitations,
  citationLabel,
  citationUrl,
  draftFileName,
  renderDraftText,
  statuteUrl,
} from "./draft.ts";
import type { Citation, GeneratedDraft, StatuteCitation } from "./types.ts";

const SECTION: StatuteCitation = {
  kind: "statute",
  section: "42 U.S.C. § 7412(b)",
  document_id: "usc-42-chap85",
  proposition: "Congress established a list of hazardous air pollutants.",
};

const RECORD: Citation = {
  kind: "record",
  record_id: "110000350053",
  dataset: "echo",
  proposition: "This facility holds a Title V operating permit.",
};

function stamped(overrides: Partial<GeneratedDraft["document"]> = {}): GeneratedDraft {
  return {
    document: {
      document_type: "public_comment_letter",
      draft_notice:
        "DRAFT FOR HUMAN REVIEW. This document was assembled by an automated tool. It is not legal advice.",
      citations: [SECTION, RECORD],
      paragraphs: [
        { text: "Eleven permitted sources operate within ten kilometres.", citations: [RECORD] },
        { text: "The statute requires a public comment period.", citations: [SECTION] },
      ],
      recipient: "Louisiana Department of Environmental Quality",
      subject: "Comment on a pending permit renewal",
      requested_action: "Hold a public hearing.",
      ...overrides,
    },
    h3: "88444600ddfffff",
    confidence_band: "moderate",
    methodology_version: "0.1.4",
    corpus_version: "appendix-b-4ff29b03c9be",
    prompt_version: "v1",
    model: "gpt-4o",
    generated_at: "2026-09-11T16:04:59Z",
    review_required: true,
  };
}

describe("citation links", () => {
  it("sends a US Code citation to a page showing that section", () => {
    expect(statuteUrl(SECTION)).toBe("https://www.law.cornell.edu/uscode/text/42/7412");
  });

  it("handles a suffixed section number", () => {
    expect(statuteUrl({ ...SECTION, section: "42 U.S.C. § 2000d-1" })).toBe(
      "https://www.law.cornell.edu/uscode/text/42/2000d-1",
    );
  });

  it("sends a regulation to the eCFR", () => {
    expect(statuteUrl({ ...SECTION, section: "40 C.F.R. § 7.35" })).toBe(
      "https://www.ecfr.gov/current/title-40/section-7.35",
    );
  });

  it("sends a record to its EPA facility report", () => {
    expect(citationUrl(RECORD)).toContain("echo.epa.gov");
    expect(citationUrl(RECORD)).toContain("110000350053");
  });

  it("returns nothing rather than a guess for case law", () => {
    // A link that lands on the wrong page is worse than no link: the reader
    // believes they have checked.
    expect(statuteUrl({ ...SECTION, section: "532 U.S. 275 (2001)" })).toBeNull();
  });

  it("returns nothing for a citation it does not recognise", () => {
    expect(statuteUrl({ ...SECTION, section: "La. R.S. 30:2001" })).toBeNull();
  });

  it("labels a citation by what a reader would look up", () => {
    expect(citationLabel(SECTION)).toBe("42 U.S.C. § 7412(b)");
    expect(citationLabel(RECORD)).toBe("110000350053");
  });
});

const TITLE_VI: StatuteCitation = {
  kind: "statute",
  section: "42 U.S.C. § 2000d",
  document_id: "usc-42-chap21",
  proposition: "No person shall be subjected to discrimination under a federally funded program.",
};

const FIGURE_SOURCE: StatuteCitation = {
  kind: "statute",
  section: "40 C.F.R. § 51.166",
  document_id: "cfr-40-51",
  proposition: "Prevention of significant deterioration review applies to this source.",
};

describe("every citation the document makes", () => {
  it("includes the legal basis a complaint rests on", () => {
    // The legal basis is what makes the document an administrative complaint
    // rather than a letter of concern. A reader checking the citations is
    // entitled to find the authority it rests on among them.
    const citations = allCitations(
      stamped({
        document_type: "agency_complaint_draft",
        legal_basis: [TITLE_VI],
      }).document,
    );

    expect(citations.map(citationLabel)).toContain("42 U.S.C. § 2000d");
  });

  it("includes the source behind each key figure", () => {
    const citations = allCitations(
      stamped({
        key_figures: [{ label: "Cancer risk", value: "62", unit: "", citation: FIGURE_SOURCE }],
      }).document,
    );

    expect(citations.map(citationLabel)).toContain("40 C.F.R. § 51.166");
  });

  it("lists a citation once, however many places it is used", () => {
    const citations = allCitations(stamped({ legal_basis: [SECTION] }).document);

    expect(citations.filter((c) => citationLabel(c) === SECTION.section)).toHaveLength(1);
  });

  it("keeps a second proposition on an already-cited section as its own line", () => {
    // Two claims on one section are two claims, and each was verified
    // separately. Collapsing them would hide one of them from the reader.
    const second: StatuteCitation = { ...SECTION, proposition: "Something else entirely." };
    const citations = allCitations(stamped({ legal_basis: [second] }).document);

    expect(citations.filter((c) => citationLabel(c) === SECTION.section)).toHaveLength(2);
  });
});

describe("rendering a draft for the clipboard", () => {
  it("carries the legal basis of a complaint into the text", () => {
    const text = renderDraftText(
      stamped({
        document_type: "agency_complaint_draft",
        recipient_office: "EPA Office of External Civil Rights Compliance",
        legal_basis: [TITLE_VI],
        relief_sought: "An investigation.",
      }),
    );

    expect(text).toContain("Legal basis");
    expect(text).toContain("42 U.S.C. § 2000d");
    expect(text).toContain("subjected to discrimination");
    expect(text).toContain("https://www.law.cornell.edu/uscode/text/42/2000d");
  });

  it("lists a key figure's source among the citations", () => {
    const text = renderDraftText(
      stamped({
        document_type: "journalist_fact_sheet",
        key_figures: [{ label: "Cancer risk", value: "62", unit: "", citation: FIGURE_SOURCE }],
      }),
    );

    expect(text).toContain("https://www.ecfr.gov/current/title-40/section-51.166");
  });

  it("puts the draft notice first", () => {
    // People paste rather than screenshot. A document that leaves here without
    // its notice is the failure this line prevents.
    const text = renderDraftText(stamped());

    expect(text.startsWith("DRAFT FOR HUMAN REVIEW.")).toBe(true);
    expect(text).toContain("not legal advice");
  });

  it("marks each paragraph with the citations behind it", () => {
    const text = renderDraftText(stamped());

    expect(text).toContain("within ten kilometres. [110000350053]");
    expect(text).toContain("public comment period. [42 U.S.C. § 7412(b)]");
  });

  it("lists every citation with a URL a reader can follow", () => {
    const text = renderDraftText(stamped());

    expect(text).toContain("https://www.law.cornell.edu/uscode/text/42/7412");
    expect(text).toContain("echo.epa.gov");
  });

  it("carries the propositions, so a pasted draft says what each citation is for", () => {
    expect(renderDraftText(stamped())).toContain(
      "Congress established a list of hazardous air pollutants.",
    );
  });

  it("records which corpus, prompt and methodology produced it", () => {
    const text = renderDraftText(stamped());

    expect(text).toContain("appendix-b-4ff29b03c9be");
    expect(text).toContain("prompt v1");
    expect(text).toContain("Methodology 0.1.4");
  });

  it("says the citations were checked before the draft was shown", () => {
    expect(renderDraftText(stamped())).toContain("checked against the data and the statute corpus");
  });

  it("renders a fact sheet's figures and caveats", () => {
    const text = renderDraftText(
      stamped({
        document_type: "journalist_fact_sheet",
        headline: "Eleven permitted sources within ten kilometres",
        key_figures: [
          { label: "Facilities", value: "11", unit: "", citation: RECORD },
          { label: "Cancer risk", value: "62", unit: "per million", citation: SECTION },
        ],
        caveats: ["Louisiana percentiles are not national percentiles."],
      }),
    );

    expect(text).toContain("- Facilities: 11 [110000350053]");
    expect(text).toContain("- Cancer risk: 62 per million");
    expect(text).toContain("Louisiana percentiles are not national percentiles.");
  });

  it("renders a complaint's filing note so the forum is unmistakable", () => {
    const text = renderDraftText(
      stamped({
        document_type: "agency_complaint_draft",
        recipient_office: "U.S. EPA External Civil Rights Compliance Office",
        filing_note: "This is an administrative complaint. It is not a lawsuit.",
        relief_sought: "Open an investigation.",
      }),
    );

    expect(text).toContain("not a lawsuit");
    expect(text).toContain("Relief sought: Open an investigation.");
  });

  it("names the file by document type, hexagon and day", () => {
    expect(draftFileName(stamped())).toBe(
      "clearskies-draft-public_comment_letter-88444600ddfffff-2026-09-11.txt",
    );
  });
});
