CREATE TYPE "public"."facility_status" AS ENUM('operating', 'proposed', 'under_construction', 'idle', 'closed');--> statement-breakpoint
CREATE TYPE "public"."release_medium" AS ENUM('air', 'water', 'land', 'underground_injection', 'off_site');--> statement-breakpoint
CREATE TYPE "public"."report_category" AS ENUM('odor', 'smoke', 'dust', 'noise', 'water_contamination', 'illegal_dumping', 'health_symptoms', 'other');--> statement-breakpoint
CREATE TYPE "public"."report_status" AS ENUM('submitted', 'under_review', 'verified', 'rejected', 'escalated');--> statement-breakpoint
CREATE TABLE "communities" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"geoid" text NOT NULL,
	"name" text,
	"county_name" text,
	"region" text,
	"country_code" text DEFAULT 'US' NOT NULL,
	"boundary" geometry(MultiPolygon, 4326) NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "community_demographics" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"community_id" uuid NOT NULL,
	"survey_year" smallint NOT NULL,
	"source" text NOT NULL,
	"population" integer,
	"median_household_income" integer,
	"poverty_rate" double precision,
	"minority_share" double precision,
	"limited_english_share" double precision,
	"under_5_share" double precision,
	"over_64_share" double precision,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "poverty_rate_range" CHECK ("community_demographics"."poverty_rate" between 0 and 1),
	CONSTRAINT "minority_share_range" CHECK ("community_demographics"."minority_share" between 0 and 1),
	CONSTRAINT "limited_english_share_range" CHECK ("community_demographics"."limited_english_share" between 0 and 1),
	CONSTRAINT "under_5_share_range" CHECK ("community_demographics"."under_5_share" between 0 and 1),
	CONSTRAINT "over_64_share_range" CHECK ("community_demographics"."over_64_share" between 0 and 1)
);
--> statement-breakpoint
CREATE TABLE "community_reports" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"category" "report_category" NOT NULL,
	"status" "report_status" DEFAULT 'submitted' NOT NULL,
	"description" text NOT NULL,
	"location" geometry(Point, 4326) NOT NULL,
	"observed_at" timestamp with time zone NOT NULL,
	"facility_id" uuid,
	"community_id" uuid,
	"reporter_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "corporations" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"parent_id" uuid,
	"ticker_symbol" text,
	"country_code" text,
	"website" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "emissions" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"facility_id" uuid NOT NULL,
	"pollutant_id" uuid NOT NULL,
	"reporting_year" smallint NOT NULL,
	"medium" "release_medium" NOT NULL,
	"amount_kg" numeric(20, 4) NOT NULL,
	"source" text NOT NULL,
	"source_url" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "emissions_amount_nonneg" CHECK ("emissions"."amount_kg" >= 0)
);
--> statement-breakpoint
CREATE TABLE "facilities" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"corporation_id" uuid,
	"registry_id" text,
	"naics_code" text,
	"industry_sector" text,
	"status" "facility_status" DEFAULT 'operating' NOT NULL,
	"address" text,
	"city" text,
	"region" text,
	"postal_code" text,
	"country_code" text DEFAULT 'US' NOT NULL,
	"location" geometry(Point, 4326) NOT NULL,
	"opened_on" date,
	"closed_on" date,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "pollutants" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"name" text NOT NULL,
	"cas_number" text,
	"category" text,
	"is_carcinogen" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "report_attachments" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"report_id" uuid NOT NULL,
	"object_key" text NOT NULL,
	"content_type" text NOT NULL,
	"size_bytes" bigint NOT NULL,
	"sha256" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "report_attachments_size_nonneg" CHECK ("report_attachments"."size_bytes" >= 0)
);
--> statement-breakpoint
CREATE TABLE "violations" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"facility_id" uuid NOT NULL,
	"agency" text NOT NULL,
	"statute" text,
	"case_number" text,
	"description" text,
	"violation_date" date,
	"resolved_on" date,
	"penalty_amount_minor" bigint,
	"penalty_currency" text DEFAULT 'USD',
	"source_url" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "community_demographics" ADD CONSTRAINT "community_demographics_community_id_communities_id_fk" FOREIGN KEY ("community_id") REFERENCES "public"."communities"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "community_reports" ADD CONSTRAINT "community_reports_facility_id_facilities_id_fk" FOREIGN KEY ("facility_id") REFERENCES "public"."facilities"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "community_reports" ADD CONSTRAINT "community_reports_community_id_communities_id_fk" FOREIGN KEY ("community_id") REFERENCES "public"."communities"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "corporations" ADD CONSTRAINT "corporations_parent_id_corporations_id_fk" FOREIGN KEY ("parent_id") REFERENCES "public"."corporations"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "emissions" ADD CONSTRAINT "emissions_facility_id_facilities_id_fk" FOREIGN KEY ("facility_id") REFERENCES "public"."facilities"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "emissions" ADD CONSTRAINT "emissions_pollutant_id_pollutants_id_fk" FOREIGN KEY ("pollutant_id") REFERENCES "public"."pollutants"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "facilities" ADD CONSTRAINT "facilities_corporation_id_corporations_id_fk" FOREIGN KEY ("corporation_id") REFERENCES "public"."corporations"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "report_attachments" ADD CONSTRAINT "report_attachments_report_id_community_reports_id_fk" FOREIGN KEY ("report_id") REFERENCES "public"."community_reports"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "violations" ADD CONSTRAINT "violations_facility_id_facilities_id_fk" FOREIGN KEY ("facility_id") REFERENCES "public"."facilities"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "communities_geoid_uq" ON "communities" USING btree ("country_code","geoid");--> statement-breakpoint
CREATE INDEX "communities_boundary_gix" ON "communities" USING gist ("boundary");--> statement-breakpoint
CREATE UNIQUE INDEX "community_demographics_year_uq" ON "community_demographics" USING btree ("community_id","survey_year","source");--> statement-breakpoint
CREATE INDEX "community_reports_location_gix" ON "community_reports" USING gist ("location");--> statement-breakpoint
CREATE INDEX "community_reports_status_idx" ON "community_reports" USING btree ("status","created_at");--> statement-breakpoint
CREATE INDEX "community_reports_facility_idx" ON "community_reports" USING btree ("facility_id");--> statement-breakpoint
CREATE UNIQUE INDEX "corporations_name_uq" ON "corporations" USING btree (lower("name"));--> statement-breakpoint
CREATE INDEX "corporations_parent_idx" ON "corporations" USING btree ("parent_id");--> statement-breakpoint
CREATE UNIQUE INDEX "emissions_natural_uq" ON "emissions" USING btree ("facility_id","pollutant_id","reporting_year","medium","source");--> statement-breakpoint
CREATE INDEX "emissions_pollutant_year_idx" ON "emissions" USING btree ("pollutant_id","reporting_year");--> statement-breakpoint
CREATE UNIQUE INDEX "facilities_registry_id_uq" ON "facilities" USING btree ("registry_id");--> statement-breakpoint
CREATE INDEX "facilities_corporation_idx" ON "facilities" USING btree ("corporation_id");--> statement-breakpoint
CREATE INDEX "facilities_location_gix" ON "facilities" USING gist ("location");--> statement-breakpoint
CREATE INDEX "facilities_naics_idx" ON "facilities" USING btree ("naics_code");--> statement-breakpoint
CREATE UNIQUE INDEX "pollutants_cas_uq" ON "pollutants" USING btree ("cas_number");--> statement-breakpoint
CREATE UNIQUE INDEX "pollutants_name_uq" ON "pollutants" USING btree (lower("name"));--> statement-breakpoint
CREATE UNIQUE INDEX "report_attachments_object_key_uq" ON "report_attachments" USING btree ("object_key");--> statement-breakpoint
CREATE INDEX "report_attachments_report_idx" ON "report_attachments" USING btree ("report_id");--> statement-breakpoint
CREATE INDEX "violations_facility_idx" ON "violations" USING btree ("facility_id","violation_date");--> statement-breakpoint
CREATE UNIQUE INDEX "violations_case_uq" ON "violations" USING btree ("agency","case_number");