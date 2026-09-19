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

// ---- The drafting assistant (CS-303, CS-306) ---------------------------
//
// Mirrors api/app/assistant/documents.py and guardrails.py. Two shapes encode a
// safety property rather than data: `DraftableBand` has no "insufficient"
// member, and a citation is a discriminated union rather than a string. Both
// mean the failure they prevent cannot be represented on this side either.

export type DocumentType =
  | "public_comment_letter"
  | "agency_complaint_draft"
  | "community_briefing_sheet"
  | "journalist_fact_sheet";

/** Section 12's bands, minus the one that cannot be drafted from. */
export type DraftableBand = "high" | "moderate" | "low";

export interface StatuteCitation {
  kind: "statute";
  section: string;
  document_id: string;
  proposition: string;
}

export interface RecordCitation {
  kind: "record";
  record_id: string;
  dataset: string;
  proposition: string;
}

export type Citation = StatuteCitation | RecordCitation;

export interface DraftParagraph {
  text: string;
  citations: Citation[];
}

export interface KeyFigure {
  label: string;
  value: string;
  unit: string;
  citation: Citation;
}

/** Every document type's fields. The optional ones belong to one type each. */
export interface DraftDocument {
  document_type: DocumentType;
  paragraphs: DraftParagraph[];
  draft_notice: string;
  citations: Citation[];

  // public_comment_letter
  recipient?: string;
  subject?: string;
  docket_reference?: string | null;
  requested_action?: string;

  // agency_complaint_draft
  forum?: "administrative_complaint";
  recipient_office?: string;
  legal_basis?: StatuteCitation[];
  relief_sought?: string;
  filing_note?: string;

  // community_briefing_sheet
  headline?: string;
  area_description?: string;
  what_this_means?: string;
  what_you_can_do?: string[];

  // journalist_fact_sheet
  key_figures?: KeyFigure[];
  caveats?: string[];
}

export interface GeneratedDraft {
  document: DraftDocument;
  h3: string;
  confidence_band: DraftableBand;
  methodology_version: string;
  corpus_version: string;
  prompt_version: string;
  model: string;
  generated_at: string;
  review_required: true;
}

export type RefusalReason =
  | "no_supporting_authority"
  | "insufficient_data"
  | "would_require_prohibited_claim"
  | "request_seeks_legal_advice"
  | "request_out_of_scope";

export interface Refusal {
  refused: true;
  reason: RefusalReason;
  explanation: string;
  missing: string[];
}

export interface DraftResponse {
  status: "drafted" | "refused";
  draft: GeneratedDraft | null;
  refusal: Refusal | null;
  from_cache: boolean;
}

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  public_comment_letter: "Public comment letter",
  agency_complaint_draft: "Agency complaint",
  community_briefing_sheet: "Community briefing sheet",
  journalist_fact_sheet: "Journalist fact sheet",
};

export const DOCUMENT_TYPE_BLURBS: Record<DocumentType, string> = {
  public_comment_letter: "For a permit proceeding, addressed to the agency's docket.",
  agency_complaint_draft: "An administrative complaint to a civil rights or environmental office.",
  community_briefing_sheet: "Plain language, for the people who live here.",
  journalist_fact_sheet: "Checkable figures, each with the record it came from.",
};
