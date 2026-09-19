import { relations, sql } from "drizzle-orm";
import {
  bigint,
  bigserial,
  boolean,
  check,
  customType,
  date,
  doublePrecision,
  index,
  integer,
  numeric,
  pgEnum,
  pgTable,
  smallint,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

// All geometry is WGS 84 (SRID 4326) so facilities and communities can be
// compared directly. Drizzle's built-in `geometry` column ignores `srid` and
// writes SRID 0, so points use a custom type instead.
export type LngLat = { lng: number; lat: number };

type GeoJsonPoint = { type: "Point"; coordinates: [number, number] };

const point4326 = customType<{ data: LngLat; driverData: string | GeoJsonPoint }>({
  dataType: () => "geometry(Point, 4326)",
  toDriver: ({ lng, lat }) => `SRID=4326;POINT(${lng} ${lat})`,
  // Top-level selects return hex EWKB; nested relational queries go through
  // json_build_array, which PostGIS renders as GeoJSON.
  fromDriver: (value) =>
    typeof value === "string"
      ? parseEwkbPoint(value)
      : { lng: value.coordinates[0], lat: value.coordinates[1] },
});

// Polygons are written as EWKT/GeoJSON via PostGIS functions and read back
// with ST_AsGeoJSON, so the raw column value is left as the driver's hex.
const multiPolygon4326 = customType<{ data: string }>({
  dataType: () => "geometry(MultiPolygon, 4326)",
});

function parseEwkbPoint(hex: string): LngLat {
  const buf = Buffer.from(hex, "hex");
  const le = buf.readUInt8(0) === 1;
  const type = le ? buf.readUInt32LE(1) : buf.readUInt32BE(1);
  let offset = 5;
  if (type & 0x20000000) offset += 4; // skip embedded SRID
  const readDouble = (o: number) => (le ? buf.readDoubleLE(o) : buf.readDoubleBE(o));
  return { lng: readDouble(offset), lat: readDouble(offset + 8) };
}

const timestamps = {
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow()
    .$onUpdate(() => new Date()),
};

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export const facilityStatus = pgEnum("facility_status", [
  "operating",
  "proposed",
  "under_construction",
  "idle",
  "closed",
]);

export const releaseMedium = pgEnum("release_medium", ["air", "water", "land", "underground_injection", "off_site"]);

export const reportCategory = pgEnum("report_category", [
  "odor",
  "smoke",
  "dust",
  "noise",
  "water_contamination",
  "illegal_dumping",
  "health_symptoms",
  "other",
]);

export const reportStatus = pgEnum("report_status", ["submitted", "under_review", "verified", "rejected", "escalated"]);

// ---------------------------------------------------------------------------
// Corporations: who owns the polluting facilities
// ---------------------------------------------------------------------------

export const corporations = pgTable(
  "corporations",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    name: text("name").notNull(),
    // Subsidiaries roll up to a parent so exposure can be aggregated.
    parentId: uuid("parent_id").references((): any => corporations.id, { onDelete: "set null" }),
    tickerSymbol: text("ticker_symbol"),
    countryCode: text("country_code"),
    website: text("website"),
    ...timestamps,
  },
  (t) => [
    uniqueIndex("corporations_name_uq").on(sql`lower(${t.name})`),
    index("corporations_parent_idx").on(t.parentId),
  ],
);

// ---------------------------------------------------------------------------
// Facilities: industrial sites with a location
// ---------------------------------------------------------------------------

export const facilities = pgTable(
  "facilities",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    name: text("name").notNull(),
    corporationId: uuid("corporation_id").references(() => corporations.id, { onDelete: "set null" }),
    // e.g. EPA Facility Registry Service ID, for de-duplicating imports.
    registryId: text("registry_id"),
    naicsCode: text("naics_code"),
    industrySector: text("industry_sector"),
    status: facilityStatus("status").notNull().default("operating"),
    address: text("address"),
    city: text("city"),
    region: text("region"),
    postalCode: text("postal_code"),
    countryCode: text("country_code").notNull().default("US"),
    location: point4326("location").notNull(),
    openedOn: date("opened_on"),
    closedOn: date("closed_on"),
    ...timestamps,
  },
  (t) => [
    uniqueIndex("facilities_registry_id_uq").on(t.registryId),
    index("facilities_corporation_idx").on(t.corporationId),
    index("facilities_location_gix").using("gist", t.location),
    index("facilities_naics_idx").on(t.naicsCode),
  ],
);

// ---------------------------------------------------------------------------
// Communities: census tracts (or equivalent) with demographics
// ---------------------------------------------------------------------------

export const communities = pgTable(
  "communities",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    // Census GEOID for US tracts; other countries use their own codes.
    geoid: text("geoid").notNull(),
    name: text("name"),
    countyName: text("county_name"),
    region: text("region"),
    countryCode: text("country_code").notNull().default("US"),
    boundary: multiPolygon4326("boundary").notNull(),
    ...timestamps,
  },
  (t) => [
    uniqueIndex("communities_geoid_uq").on(t.countryCode, t.geoid),
    index("communities_boundary_gix").using("gist", t.boundary),
  ],
);

// Demographics change over time, so they're versioned by survey year.
export const communityDemographics = pgTable(
  "community_demographics",
  {
    id: bigserial("id", { mode: "number" }).primaryKey(),
    communityId: uuid("community_id")
      .notNull()
      .references(() => communities.id, { onDelete: "cascade" }),
    surveyYear: smallint("survey_year").notNull(),
    source: text("source").notNull(), // e.g. "ACS 5-year"
    population: integer("population"),
    medianHouseholdIncome: integer("median_household_income"),
    povertyRate: doublePrecision("poverty_rate"),
    // Share of residents who are people of color, 0..1.
    minorityShare: doublePrecision("minority_share"),
    limitedEnglishShare: doublePrecision("limited_english_share"),
    under5Share: doublePrecision("under_5_share"),
    over64Share: doublePrecision("over_64_share"),
    createdAt: timestamps.createdAt,
  },
  (t) => [
    uniqueIndex("community_demographics_year_uq").on(t.communityId, t.surveyYear, t.source),
    check("poverty_rate_range", sql`${t.povertyRate} between 0 and 1`),
    check("minority_share_range", sql`${t.minorityShare} between 0 and 1`),
    check("limited_english_share_range", sql`${t.limitedEnglishShare} between 0 and 1`),
    check("under_5_share_range", sql`${t.under5Share} between 0 and 1`),
    check("over_64_share_range", sql`${t.over64Share} between 0 and 1`),
  ],
);

// ---------------------------------------------------------------------------
// Pollutants and reported emissions
// ---------------------------------------------------------------------------

export const pollutants = pgTable(
  "pollutants",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    name: text("name").notNull(),
    casNumber: text("cas_number"),
    category: text("category"), // e.g. "VOC", "heavy metal", "PM2.5"
    isCarcinogen: boolean("is_carcinogen").notNull().default(false),
    ...timestamps,
  },
  (t) => [
    uniqueIndex("pollutants_cas_uq").on(t.casNumber),
    uniqueIndex("pollutants_name_uq").on(sql`lower(${t.name})`),
  ],
);

export const emissions = pgTable(
  "emissions",
  {
    id: bigserial("id", { mode: "number" }).primaryKey(),
    facilityId: uuid("facility_id")
      .notNull()
      .references(() => facilities.id, { onDelete: "cascade" }),
    pollutantId: uuid("pollutant_id")
      .notNull()
      .references(() => pollutants.id, { onDelete: "restrict" }),
    reportingYear: smallint("reporting_year").notNull(),
    medium: releaseMedium("medium").notNull(),
    // Normalised to kilograms so facilities can be compared.
    amountKg: numeric("amount_kg", { precision: 20, scale: 4 }).notNull(),
    source: text("source").notNull(), // e.g. "EPA TRI"
    sourceUrl: text("source_url"),
    createdAt: timestamps.createdAt,
  },
  (t) => [
    uniqueIndex("emissions_natural_uq").on(t.facilityId, t.pollutantId, t.reportingYear, t.medium, t.source),
    index("emissions_pollutant_year_idx").on(t.pollutantId, t.reportingYear),
    check("emissions_amount_nonneg", sql`${t.amountKg} >= 0`),
  ],
);

// ---------------------------------------------------------------------------
// Regulatory violations and enforcement
// ---------------------------------------------------------------------------

export const violations = pgTable(
  "violations",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    facilityId: uuid("facility_id")
      .notNull()
      .references(() => facilities.id, { onDelete: "cascade" }),
    agency: text("agency").notNull(),
    statute: text("statute"), // e.g. "Clean Air Act"
    caseNumber: text("case_number"),
    description: text("description"),
    violationDate: date("violation_date"),
    resolvedOn: date("resolved_on"),
    // Stored in minor units (cents) to avoid float rounding.
    penaltyAmountMinor: bigint("penalty_amount_minor", { mode: "number" }),
    penaltyCurrency: text("penalty_currency").default("USD"),
    sourceUrl: text("source_url"),
    ...timestamps,
  },
  (t) => [
    index("violations_facility_idx").on(t.facilityId, t.violationDate),
    uniqueIndex("violations_case_uq").on(t.agency, t.caseNumber),
  ],
);

// ---------------------------------------------------------------------------
// Community reports: residents documenting what they see and smell
// ---------------------------------------------------------------------------

export const communityReports = pgTable(
  "community_reports",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    category: reportCategory("category").notNull(),
    status: reportStatus("status").notNull().default("submitted"),
    description: text("description").notNull(),
    location: point4326("location").notNull(),
    observedAt: timestamp("observed_at", { withTimezone: true }).notNull(),
    // Optional links; reviewers can attach these after triage.
    facilityId: uuid("facility_id").references(() => facilities.id, { onDelete: "set null" }),
    communityId: uuid("community_id").references(() => communities.id, { onDelete: "set null" }),
    // Opaque reporter reference; no PII stored here by design.
    reporterId: text("reporter_id"),
    ...timestamps,
  },
  (t) => [
    index("community_reports_location_gix").using("gist", t.location),
    index("community_reports_status_idx").on(t.status, t.createdAt),
    index("community_reports_facility_idx").on(t.facilityId),
  ],
);

// Photos, videos and documents live in the `clearskies` bucket; only the key
// and metadata are stored here.
export const reportAttachments = pgTable(
  "report_attachments",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    reportId: uuid("report_id")
      .notNull()
      .references(() => communityReports.id, { onDelete: "cascade" }),
    objectKey: text("object_key").notNull(),
    contentType: text("content_type").notNull(),
    sizeBytes: bigint("size_bytes", { mode: "number" }).notNull(),
    sha256: text("sha256"),
    createdAt: timestamps.createdAt,
  },
  (t) => [
    uniqueIndex("report_attachments_object_key_uq").on(t.objectKey),
    index("report_attachments_report_idx").on(t.reportId),
    check("report_attachments_size_nonneg", sql`${t.sizeBytes} >= 0`),
  ],
);

// ---------------------------------------------------------------------------
// Relations (for the relational query API)
// ---------------------------------------------------------------------------

export const corporationsRelations = relations(corporations, ({ one, many }) => ({
  parent: one(corporations, {
    fields: [corporations.parentId],
    references: [corporations.id],
    relationName: "subsidiaries",
  }),
  subsidiaries: many(corporations, { relationName: "subsidiaries" }),
  facilities: many(facilities),
}));

export const facilitiesRelations = relations(facilities, ({ one, many }) => ({
  corporation: one(corporations, { fields: [facilities.corporationId], references: [corporations.id] }),
  emissions: many(emissions),
  violations: many(violations),
  reports: many(communityReports),
}));

export const communitiesRelations = relations(communities, ({ many }) => ({
  demographics: many(communityDemographics),
  reports: many(communityReports),
}));

export const communityDemographicsRelations = relations(communityDemographics, ({ one }) => ({
  community: one(communities, { fields: [communityDemographics.communityId], references: [communities.id] }),
}));

export const pollutantsRelations = relations(pollutants, ({ many }) => ({
  emissions: many(emissions),
}));

export const emissionsRelations = relations(emissions, ({ one }) => ({
  facility: one(facilities, { fields: [emissions.facilityId], references: [facilities.id] }),
  pollutant: one(pollutants, { fields: [emissions.pollutantId], references: [pollutants.id] }),
}));

export const violationsRelations = relations(violations, ({ one }) => ({
  facility: one(facilities, { fields: [violations.facilityId], references: [facilities.id] }),
}));

export const communityReportsRelations = relations(communityReports, ({ one, many }) => ({
  facility: one(facilities, { fields: [communityReports.facilityId], references: [facilities.id] }),
  community: one(communities, { fields: [communityReports.communityId], references: [communities.id] }),
  attachments: many(reportAttachments),
}));

export const reportAttachmentsRelations = relations(reportAttachments, ({ one }) => ({
  report: one(communityReports, { fields: [reportAttachments.reportId], references: [communityReports.id] }),
}));
