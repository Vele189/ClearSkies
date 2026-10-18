/** The arithmetic the waterfall narrates, and the plain-language reading of a
 *  confidence value. Kept out of the component so the numbers on the panel can
 *  be tested against methodology sections 10 and 12 directly.
 *
 *  Nothing here re-derives a number the API already reports. Where a step
 *  cannot be shown — the statewide maximum that rescales a component to 0–10
 *  is not on the response — the panel says so rather than inventing it.
 */

import type {
  ComponentScore,
  Confidence,
  Facility,
  GroupScore,
  IndicatorValue,
  NoScoreReason,
} from "./types.ts";
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

/** A rank as English writes it: 1st, 2nd, 3rd, 11th, 21st, 22nd.
 *
 *  Percentiles are read aloud, and "1th" or "22th" on a panel that is asking to
 *  be trusted with a legal document is the kind of slip that makes a reader
 *  wonder what else was not checked. The teens are the whole difficulty: they
 *  take "th" whatever their last digit is.
 *
 *  Rounded to a whole rank, because that is how every caller shows one. */
export function ordinal(value: number): string {
  const rank = Math.round(value);
  const lastTwo = Math.abs(rank) % 100;
  const last = Math.abs(rank) % 10;
  const suffix =
    lastTwo >= 11 && lastTwo <= 13
      ? "th"
      : last === 1
        ? "st"
        : last === 2
          ? "nd"
          : last === 3
            ? "rd"
            : "th";
  return `${String(rank)}${suffix}`;
}

/** A percentile as a rank, held to 1st..99th.
 *
 *  Hazen percentiles never reach 0 or 100, but they come within rounding of
 *  both: the worst cell in Louisiana sits at 99.97, which `ordinal` writes as
 *  "100th". That reads as a mistake to anyone who knows what a percentile is,
 *  and a panel asking to be trusted cannot afford to look like one. */
export function percentileOrdinal(value: number): string {
  return ordinal(Math.min(99, Math.max(1, value)));
}

/** Why a hexagon has no score, as a heading and a sentence a reader can use.
 *  The API sends a code; "low population" on its own reads like a judgement
 *  about the place rather than a rule about the arithmetic. */
export const NO_SCORE_EXPLANATIONS: Record<NoScoreReason, { title: string; detail: string }> = {
  low_population: {
    title: "Too few residents to score",
    detail:
      "Fewer than 25 people are estimated to live in this hexagon, so it is left out of " +
      "the ranking rather than scored on almost no one (methodology section 5). Nearby " +
      "populated hexagons are scored.",
  },
  insufficient_pollution_data: {
    title: "Not enough pollution data to score",
    detail:
      "Too few of the pollution indicators have a value here for the pollution component " +
      "to be computed, so no score is given rather than one built on gaps.",
  },
  insufficient_population_data: {
    title: "Not enough population data to score",
    detail:
      "Too few of the population indicators have a value here for the population " +
      "component to be computed, so no score is given rather than one built on gaps.",
  },
  outside_scored_states: {
    title: "Outside Louisiana",
    detail:
      "This hexagon is in the buffer past the state line. It is part of the grid so that " +
      "facilities across the border count toward Louisiana hexagons, but it is not ranked.",
  },
};

/** "3 present, 2 needed", in words. The bare "3 of 2" this replaces read like a
 *  typo: a group can hold more indicators than its minimum requires. */
export function groupCoverage(group: GroupScore): string {
  const present = `${String(group.indicators_present)} ${
    group.indicators_present === 1 ? "indicator" : "indicators"
  }`;
  return `${present}, ${String(group.indicators_required)} needed`;
}

/** Units a reader can make sense of on their own, and how each is written.
 *  The facility indicators are distance-decayed weighted sums whose magnitude
 *  means nothing outside the ranking; for those the percentile is the reading
 *  and a raw value like 2.4e-7 would only confuse. */
const READABLE_UNITS: Record<string, (value: number) => string> = {
  "risk per million": (v) => `${formatNumber(v)} in a million`,
  "hazard index": (v) => `index ${v.toFixed(2)}`,
  "ug/m3": (v) => `${v.toFixed(1)} µg/m³`,
  percent: (v) => `${v.toFixed(1)}%`,
};

function formatNumber(value: number): string {
  if (value >= 100) return Math.round(value).toLocaleString("en-US");
  if (value >= 10) return value.toFixed(0);
  return value.toFixed(1);
}

/** The measured value, written for a reader, or null where the unit carries no
 *  meaning outside the ranking. */
export function indicatorValue(indicator: IndicatorValue): string | null {
  if (!indicator.observed || indicator.value === null) return null;
  const format = READABLE_UNITS[indicator.unit];
  return format ? format(indicator.value) : null;
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

/** What a zero means for each facility indicator. They are not all "no
 *  facility nearby": F2 and F3 are zero where facilities are present and none
 *  was out of compliance or under formal enforcement, and saying "no qualifying
 *  facility" there contradicts the facility list below it. Wording follows
 *  methodology section 8's table. */
const ZERO_MEANS: Record<string, string> = {
  E3: "No facility within 10 km reported toxic air releases to TRI.",
  F1: "No Clean Air Act major source or Title V facility within 10 km.",
  F2: "No facility within 10 km was in non-compliance in the last 12 quarters.",
  F3: "No formal enforcement action against a facility within 10 km in the last 5 years.",
  F4: "No hazardous waste generator or treatment facility within 10 km.",
};

/** The note a zero facility indicator carries on the panel, or null. */
export function zeroInflationNote(indicator: IndicatorValue): string | null {
  if (!isZeroInflated(indicator)) return null;
  return (
    `${ZERO_MEANS[indicator.id] ?? "No qualifying facility within 10 km."} This percentile ` +
    "reflects how many other hexagons are also at zero, not how this one compares on burden."
  );
}

/** One row per facility, nearest first.
 *
 *  The API lists a facility once per regulatory program, so a plant under both
 *  the Clean Air Act and RCRA appears twice with the same name and distance.
 *  Merged here, keeping every program and the worst compliance figures, so the
 *  list counts plants rather than permits. */
export interface FacilityRow extends Facility {
  programs: string[];
}

export function mergeFacilities(facilities: Facility[]): FacilityRow[] {
  const byId = new Map<string, FacilityRow>();
  for (const facility of facilities) {
    const existing = byId.get(facility.registry_id);
    if (!existing) {
      byId.set(facility.registry_id, { ...facility, programs: [facility.program] });
      continue;
    }
    if (!existing.programs.includes(facility.program)) existing.programs.push(facility.program);
    existing.distance_km = Math.min(existing.distance_km, facility.distance_km);
    existing.quarters_in_noncompliance = maxOrNull(
      existing.quarters_in_noncompliance,
      facility.quarters_in_noncompliance,
    );
    existing.formal_actions_5yr = maxOrNull(
      existing.formal_actions_5yr,
      facility.formal_actions_5yr,
    );
  }
  return [...byId.values()].sort((a, b) => a.distance_km - b.distance_km);
}

function maxOrNull(a: number | null, b: number | null): number | null {
  if (a === null) return b;
  if (b === null) return a;
  return Math.max(a, b);
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
