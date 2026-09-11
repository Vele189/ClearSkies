/** The arithmetic the waterfall narrates, and the plain-language reading of a
 *  confidence value. Kept out of the component so the numbers on the panel can
 *  be tested against methodology sections 10 and 12 directly.
 *
 *  Nothing here re-derives a number the API already reports. Where a step
 *  cannot be shown — the statewide maximum that rescales a component to 0–10
 *  is not on the response — the panel says so rather than inventing it.
 */

import type { ComponentScore, Confidence, GroupScore, IndicatorValue } from "./types.ts";
import type { Component, ConfidenceBand, Group } from "./types.ts";

export const COMPONENT_LABELS: Record<Component, string> = {
  pollution_burden: "Pollution burden",
  population_characteristics: "Population characteristics",
};

/** Methodology section 10, step 2: the weighted mean of the computable group
 *  means, in percentile units. This is the component before its rescale to
 *  0–10, which is why it is labelled as such on the panel and not as the score.
 *
 *  A group that is not computable is left out of both the numerator and the
 *  denominator, per section 11 rule 1. Averaging it in as zero would pull the
 *  component down for a hex whose data is merely absent. */
export function weightedGroupMean(groups: GroupScore[]): number | null {
  let weighted = 0;
  let weight = 0;
  for (const group of groups) {
    if (!group.computable || group.mean_percentile === null) continue;
    weighted += group.weight * group.mean_percentile;
    weight += group.weight;
  }
  return weight === 0 ? null : weighted / weight;
}

/** Groups that were dropped from their component's mean, so the panel can name
 *  them rather than leaving a reader to notice the weights do not add up. */
export function droppedGroups(groups: GroupScore[]): GroupScore[] {
  return groups.filter((g) => !g.computable || g.mean_percentile === null);
}

/** Section 10, step 4. Reported for the reader's arithmetic, not recomputed as
 *  the authority: `HexDetail.score` remains the score. A visible discrepancy
 *  between the two is a pipeline bug worth seeing rather than hiding. */
export function productOfComponents(components: ComponentScore[]): number | null {
  if (components.length === 0) return null;
  return components.reduce((total, component) => total * component.score, 1);
}

export interface ConfidenceTerm {
  id: string;
  label: string;
  /** Section 12's weights. They sum to 1.0. */
  weight: number;
  value: number;
  /** What a low value on this term actually means, in the reader's terms. */
  meaning: string;
}

export function confidenceTerms(confidence: Confidence): ConfidenceTerm[] {
  return [
    {
      id: "coverage",
      label: "Indicator coverage",
      weight: 0.35,
      value: confidence.coverage,
      meaning: "How many of the fifteen indicators had a value here",
    },
    {
      id: "recency",
      label: "Recency",
      weight: 0.2,
      value: confidence.recency,
      meaning: "How old the contributing data is",
    },
    {
      id: "spatial",
      label: "Spatial support",
      weight: 0.25,
      value: confidence.spatial_support,
      meaning: "How much of this hexagon's population is interpolated rather than measured",
    },
    {
      id: "monitor",
      label: "Monitor support",
      weight: 0.2,
      value: confidence.monitor_support,
      meaning: "How close the nearest PM2.5 monitor is",
    },
  ];
}

/** The term dragging the value down. Because the four are combined as a
 *  weighted geometric mean, one weak term is not averaged away by three healthy
 *  ones, so naming it explains the number better than the number does. */
export function weakestTerm(confidence: Confidence): ConfidenceTerm {
  return confidenceTerms(confidence).reduce((worst, term) =>
    term.value < worst.value ? term : worst,
  );
}

const BAND_READINGS: Record<ConfidenceBand, string> = {
  high: "Well supported. Read this score at face value.",
  moderate: "Reasonably supported. The score is usable, with the gaps below in mind.",
  low: "Weakly supported. Treat this score as indicative and check the gaps below before relying on it.",
  insufficient:
    "Not supported well enough for us to stand behind. This hexagon is excluded from validation statistics and cannot be used to generate a document.",
};

export function bandReading(band: ConfidenceBand): string {
  return BAND_READINGS[band];
}

/** Section 12 puts these two bands behind a caveat that leads rather than
 *  follows. On the map they are hatched; here the panel opens with the warning. */
export function leadsWithCaveat(band: ConfidenceBand): boolean {
  return band === "low" || band === "insufficient";
}

/** Facility-derived indicators. Section 9: these are zero for every hex with no
 *  qualifying source within 10 km, so a large block of the state shares one
 *  mid-rank percentile. Below it the percentile carries no information. */
const FACILITY_INDICATORS = new Set(["E3", "F1", "F2", "F3", "F4"]);

/** True when an indicator's percentile would mislead if read as a ranking.
 *  Section 9 requires this limitation to be published on the panel rather than
 *  smoothed over: for a hex with nothing nearby, these say "none within 10 km",
 *  not "cleaner than 40% of the state". */
export function isZeroInflated(indicator: IndicatorValue): boolean {
  return FACILITY_INDICATORS.has(indicator.id) && indicator.observed && indicator.value === 0;
}

/** Release identifier for an indicator's source, when CS-209 has populated it.
 *  Keyed by source name, so an indicator finds its vintage through the source
 *  it names. */
export function vintageFor(
  indicator: IndicatorValue,
  vintage: Record<string, string>,
): string | null {
  return vintage[indicator.source] ?? null;
}

export const GROUP_ORDER: Group[] = [
  "exposures",
  "environmental_effects",
  "sensitive_populations",
  "socioeconomic_factors",
];
