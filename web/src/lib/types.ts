// Mirrors api/app/schemas.py. Phase 2 generates this from the OpenAPI document
// instead of maintaining it by hand; until the shapes settle, hand-written is
// less machinery than a codegen step nobody runs.

export type Group =
  | "exposures"
  | "environmental_effects"
  | "sensitive_populations"
  | "socioeconomic_factors";

export type Component = "pollution_burden" | "population_characteristics";

export type ConfidenceBand = "high" | "moderate" | "low" | "insufficient";

export type NoScoreReason =
  | "low_population"
  | "insufficient_pollution_data"
  | "insufficient_population_data"
  | "outside_pilot_state";

export interface IndicatorValue {
  id: string;
  name: string;
  group: Group;
  value: number | null;
  unit: string;
  percentile: number | null;
  source: string;
  /** False when the indicator was absent and dropped. Never imputed. */
  observed: boolean;
}

export interface GroupScore {
  group: Group;
  mean_percentile: number | null;
  weight: number;
  indicators_present: number;
  indicators_required: number;
  computable: boolean;
}

export interface ComponentScore {
  component: Component;
  score: number;
  groups: GroupScore[];
}

export interface Confidence {
  value: number;
  band: ConfidenceBand;
  coverage: number;
  recency: number;
  spatial_support: number;
  monitor_support: number;
  nearest_monitor_km: number | null;
}

export interface Facility {
  registry_id: string;
  name: string;
  distance_km: number;
  program: string;
  echo_url: string;
  // True when the hexagon is the one containing the facility rather than merely
  // within the 10 km interaction radius. Optional to match the API model, where
  // it carries a default.
  in_hex?: boolean;
  quarters_in_noncompliance: number | null;
  formal_actions_5yr: number | null;
}

export interface Demographics {
  population: number;
  // Optional to match the API model, where every field but population carries
  // a default of null. An absent value means the ACS estimate was unavailable,
  // which is not the same as zero.
  under_5_pct?: number | null;
  over_64_pct?: number | null;
  poverty_200pct?: number | null;
  black_pct?: number | null;
  people_of_color_pct?: number | null;
  hispanic_pct?: number | null;
}

export interface HexDetail {
  h3: string;
  resolution: number;
  state: string;
  parish: string | null;
  centroid: [number, number];
  score: number | null;
  percentile: number | null;
  components: ComponentScore[];
  indicators: IndicatorValue[];
  confidence: Confidence;
  demographics: Demographics;
  facilities: Facility[];
  no_score_reason: NoScoreReason | null;
  methodology_version: string;
  data_vintage: Record<string, string>;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  pilot_state: string;
  database: "connected" | "unavailable";
  extensions: { name: string; version: string }[];
  scored_hexes: number | null;
  notes: string[];
}

export const GROUP_LABELS: Record<Group, string> = {
  exposures: "Exposures",
  environmental_effects: "Environmental effects",
  sensitive_populations: "Sensitive populations",
  socioeconomic_factors: "Socioeconomic factors",
};

export const BAND_LABELS: Record<ConfidenceBand, string> = {
  high: "High confidence",
  moderate: "Moderate confidence",
  low: "Low confidence",
  insufficient: "Insufficient data",
};
