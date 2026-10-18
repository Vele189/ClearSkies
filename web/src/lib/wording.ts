/** The words a reader sees, where the data's own words would lose them.
 *
 *  The API names things the way the methodology does ("Major source
 *  proximity", "RCRA large-quantity generator", "insufficient band"), which is
 *  right for the methodology and opaque to someone checking the air where they
 *  live. This module is where those names become plain English, so the plain
 *  versions are written once and used everywhere. The methodology's names stay
 *  in the API, the drafts and the docs; docs/frontend.md section 9 has the
 *  glossary.
 */

import { ApiError } from "./api.ts";

/** Each indicator as a reader would name it, plus one line on what it measures.
 *  Keyed by indicator id. An id missing here falls back to the API's own name. */
export const INDICATOR_WORDING: Record<string, { name: string; about: string }> = {
  E1: {
    name: "Cancer risk from toxic air",
    about: "EPA's estimate of extra cancer cases from breathing the air here over a lifetime.",
  },
  E2: {
    name: "Breathing problems from toxic air",
    about: "EPA's estimate of risk to the lungs and airways. A value of 1 is the level of concern.",
  },
  E3: {
    name: "Toxic releases from nearby plants",
    about: "Toxic chemicals plants report releasing into the air, weighted by how harmful and how close.",
  },
  E4: {
    name: "Fine-particle pollution (measured)",
    about: "Soot and dust small enough to reach the lungs, measured by the nearest air monitors.",
  },
  F1: {
    name: "Large polluters nearby",
    about: "Plants with major air pollution permits within 10 km (about 6 miles), closer ones counting more.",
  },
  F2: {
    name: "Nearby plants breaking the rules",
    about: "How often nearby plants were out of compliance with their permits in the last three years.",
  },
  F3: {
    name: "Enforcement against nearby plants",
    about: "Formal government action against nearby plants in the last five years, larger fines counting more.",
  },
  F4: {
    name: "Hazardous waste sites nearby",
    about: "Sites that produce or handle large amounts of hazardous waste within 10 km.",
  },
  S1: { name: "Young children", about: "Share of residents under 5." },
  S2: { name: "Older adults", about: "Share of residents 65 and over." },
  P1: { name: "Low income", about: "Share of residents living below twice the poverty line." },
  P2: { name: "No high school diploma", about: "Share of adults without a high school diploma." },
  P3: {
    name: "Limited English",
    about: "Share of households where no adult speaks English very well.",
  },
  P4: { name: "Unemployment", about: "Share of people who want work and cannot find it." },
  P5: { name: "High housing costs", about: "Share of households spending a large part of income on housing." },
};

/** The facility programs the API reports, as a reader would say them. */
export const PROGRAM_WORDING: Record<string, string> = {
  "Clean Air Act": "Air permit",
  "CAA Title V": "Major air permit",
  "RCRA large-quantity generator": "Hazardous waste producer",
  "RCRA treatment, storage and disposal": "Hazardous waste handler",
};

export function programWording(program: string): string {
  return PROGRAM_WORDING[program] ?? program;
}

/** Where a reader sees one of the API's error sentences, a version written for
 *  them. The API's own detail is for developers ("Check GET /health"); the
 *  status code says enough to choose what a reader should be told. */
export function readerError(error: unknown, subject = "this area"): string {
  if (!(error instanceof ApiError)) {
    return "We couldn't reach our data service. Check your connection and try again.";
  }
  switch (error.status) {
    case 404:
      return `We don't have a score for ${subject}. It may be just outside the mapped part of Louisiana.`;
    case 422:
      return "That link doesn't point to a place on the map.";
    case 429:
      return "Too many requests in a short time. Wait a moment and try again.";
    case 503:
      return "Our data service isn't available right now. Please try again in a few minutes.";
    default:
      return "Something went wrong loading this. Please try again.";
  }
}
