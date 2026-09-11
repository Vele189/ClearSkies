-- 0011: attaching facilities to hexagons, and the neighbour query that decays them
--
-- Migration 0004 gave a facility a containing cell and a positional verdict.
-- This one makes both of them do the work methodology sections 5, 6 and 8
-- actually ask for: a drill-down list of what is near a hexagon, a neighbour
-- relation the decay calculations behind E3 and F1 through F4 read, a wider
-- vocabulary for what can be wrong with a self-reported coordinate, and the
-- geocoding quality that section 12's spatial confidence term will need.
--
-- Note what is deliberately still not here. 0009 records the decision that
-- contributing facilities are derived at read time rather than materialised per
-- hex per run, because that table would be the largest in the database by a wide
-- margin to save a distance query over a few thousand rows. Nothing below
-- changes that. What it adds is the index that makes the read-time query fast
-- and the function that makes it the *same* query everywhere, so the panel and
-- the scoring step cannot drift into disagreeing about which facilities are
-- near a hexagon.

-- ---- facility.h3 is a location, not a membership claim --------------------
--
-- The foreign key from facility.h3 to hex.h3 said a facility must sit in a cell
-- the pilot-state grid contains. Section 5 says the opposite: out-of-state
-- facilities within the interaction radius count, so that a hex on the Texas
-- line near a Beaumont-area facility is not artificially clean. Such a facility
-- sits in a real resolution 8 cell that the Louisiana grid does not contain, and
-- under the old key it could not be stored at all.
--
-- So h3 records which cell the facility is in, full stop, and joins from
-- facility to hex are outer joins. Whether a facility reaches a given hexagon is
-- the neighbour query's question, answered on geometry, not a foreign key's.
ALTER TABLE facility DROP CONSTRAINT facility_h3_fkey;

COMMENT ON COLUMN facility.h3 IS
    'Resolution 8 cell containing the facility, computed in Python with h3-py. Not a '
    'foreign key: a facility outside the pilot state still has a cell, and section 5 '
    'requires it to keep contributing. Join to hex with an outer join.';

-- ---- what can be wrong with a coordinate ---------------------------------
--
-- 0004 had four verdicts. Three of the six below are the same rule split into
-- the distinct upstream defects it was blurring together, because section 6
-- publishes the exclusion count and a count is only actionable if it says what
-- went wrong:
--
--   null_island   a placeholder zero written into an empty field
--   out_of_range  not a point on Earth: a swapped sign, a truncated field
--   outside_state a real point, too far from the pilot state to be about it
--
-- The rules themselves live in etl/pipeline/geo/assignment.py, shared by every
-- source that publishes a point, so ECHO and TRI cannot reach different verdicts
-- about the same kind of coordinate.
ALTER TABLE facility DROP CONSTRAINT facility_coordinate_status_check;

ALTER TABLE facility ADD CONSTRAINT facility_coordinate_status_check
    CHECK (coordinate_status IN (
        'ok', 'missing', 'null_island', 'out_of_range', 'outside_state', 'zip_mismatch'
    ));

-- A quarantined coordinate that is still a real place keeps its geometry: a
-- reviewer asking why a facility was excluded has to be able to see where
-- upstream put it. A placeholder zero and an impossible latitude do not, because
-- writing (0, 0) into the geometry column would put a Louisiana refinery in the
-- Gulf of Guinea and leave every spatial query to remember to distrust it.
ALTER TABLE facility DROP CONSTRAINT facility_geom_matches_status;

ALTER TABLE facility ADD CONSTRAINT facility_geom_matches_status
    CHECK ((geom IS NULL) = (coordinate_status IN ('missing', 'null_island', 'out_of_range')));

-- ---- geocoding quality ---------------------------------------------------
--
-- coordinate_status says whether a facility may enter a proximity indicator.
-- This says how much the coordinate is worth, which is a different question and
-- the one section 12's c_spatial term asks. The band is a ladder over two
-- independent pieces of evidence: whether the ZIP-centroid check of section 6
-- could run and passed, and EPA's own positional accuracy estimate.
--
--   verified    passed the ZIP check, and EPA's accuracy estimate is within 100 m
--   plausible   passed the ZIP check, accuracy unknown or coarse
--   unverified  the check could not run: no ZIP, or one the gazetteer lacks
--   suspect     failed the ZIP check, or fell outside the pilot envelope
--   absent      there is no coordinate to judge
--
-- 'unverified' exists because a check that could not run is not a check that
-- passed, and 0004 recorded that distinction only in the run manifest, where a
-- later reader of the table could not get at it.
ALTER TABLE facility
    ADD COLUMN geocode_quality text NOT NULL DEFAULT 'unverified',
    ADD COLUMN geocode_accuracy_m numeric CHECK (geocode_accuracy_m >= 0),
    ADD COLUMN reported_latitude numeric,
    ADD COLUMN reported_longitude numeric;

ALTER TABLE facility ADD CONSTRAINT facility_geocode_quality_check
    CHECK (geocode_quality IN ('verified', 'plausible', 'unverified', 'suspect', 'absent'));

-- The two columns describe one verdict, so the schema refuses the combinations
-- that would mean nothing: a usable coordinate marked 'absent', or a quarantined
-- one marked 'verified'.
ALTER TABLE facility ADD CONSTRAINT facility_quality_matches_status
    CHECK (CASE coordinate_status
        WHEN 'ok'            THEN geocode_quality IN ('verified', 'plausible', 'unverified')
        WHEN 'outside_state' THEN geocode_quality = 'suspect'
        WHEN 'zip_mismatch'  THEN geocode_quality = 'suspect'
        ELSE geocode_quality = 'absent'
    END);

COMMENT ON COLUMN facility.geocode_quality IS
    'How well established the coordinate is, section 12''s c_spatial input. Distinct from '
    'coordinate_status, which is whether the facility may enter a proximity indicator.';
COMMENT ON COLUMN facility.geocode_accuracy_m IS
    'EPA''s own positional accuracy estimate, CALCULATED_ACCURACY_METERS. It exceeds 2 km '
    'for roughly three quarters of Louisiana air facilities, which is why section 6 does '
    'not simply trust the coordinate.';
COMMENT ON COLUMN facility.reported_latitude IS
    'Exactly what upstream reported, kept whatever the verdict so that a quarantine is '
    'auditable rather than taken on trust. geom holds it only when it is a real place.';

-- ---- the indexes the read path needs -------------------------------------
--
-- 0004 indexed geom as geometry. A 10 km radius is a distance on the ground, and
-- a degree of longitude at 30 degrees north is 13% shorter than a degree of
-- latitude, so the query has to ask in metres on the spheroid: ST_DWithin over
-- geography. That cannot use a geometry index, hence the expression indexes.
-- They must match the query's cast exactly or the planner falls back to a scan.
--
-- Partial on coordinate_status = 'ok' for the same reason 0004's is: section 6
-- keeps quarantined facilities in the table and out of the indicators, so the
-- index over the rows that can be returned is both smaller and the whole set.
CREATE INDEX facility_geography_idx ON facility USING gist ((geom::geography))
    WHERE coordinate_status = 'ok';

CREATE INDEX hex_centroid_geography_idx ON hex USING gist ((centroid::geography));

-- ---- the decay kernel ----------------------------------------------------
--
-- Methodology section 8.1, the denominator of E3, which F1 through F4 reuse
-- without the toxicity weighting:
--
--     1 / max(d, 250 m)^2
--
-- The 250 m floor prevents a singularity when a facility sits inside the hexagon
-- it is being scored against; without it a facility at the centroid contributes
-- infinity. Defined once, here, so that the panel and the scoring step cannot
-- decay the same facility differently.
CREATE FUNCTION facility_decay_weight(distance_m double precision)
    RETURNS double precision
    LANGUAGE sql
    IMMUTABLE
    STRICT
    PARALLEL SAFE
    AS 'SELECT 1.0::double precision / (greatest(distance_m, 250.0::double precision) ^ 2)';

COMMENT ON FUNCTION facility_decay_weight(double precision) IS
    'Inverse-square decay with a 250 m floor. Methodology section 8.1.';

-- ---- the neighbour relation ----------------------------------------------
--
-- One hexagon, every facility whose releases or permits reach it, and how much
-- each one is decayed. This is the join the drill-down panel renders and the
-- join the scoring step aggregates, and it is one function so that they are the
-- same join.
--
-- The radius is a parameter with the section 8.1 default rather than a constant
-- baked into the body, because the pipeline passes it explicitly: Python owns
-- the number, the way it owns the H3 resolution. Beyond 10 km the inverse-square
-- term has fallen far enough that including a facility costs computation without
-- changing ranks.
--
-- Nothing here filters on state. That is the point. A facility is near a hexagon
-- or it is not, and section 5 requires an out-of-state facility within the
-- interaction radius to count so that a hex on the Texas line near a
-- Beaumont-area facility is not artificially clean. The only filter is
-- coordinate_status = 'ok', which is section 6's positional rule and the same
-- set the partial index above covers.
--
-- Unordered, deliberately. It is a relation, and the caller that wants it
-- nearest first is facilities_near_hex, which sorts a few dozen rows. Sorting
-- here would sort them again for every one of 150,000 hexagons in the bulk form
-- below, to no purpose.
CREATE TYPE hex_facility_link AS (
    h3            h3_cell,
    facility_id   text,
    distance_m    double precision,
    decay_weight  double precision,
    is_containing boolean
);

COMMENT ON TYPE hex_facility_link IS
    'One hexagon-facility pair within the interaction radius, with its decay weight.';

CREATE FUNCTION hex_facility_links(cell h3_cell, radius_m double precision DEFAULT 10000)
    RETURNS SETOF hex_facility_link
    LANGUAGE sql
    STABLE
    PARALLEL SAFE
    AS '
        SELECT near.h3,
               near.facility_id,
               near.distance_m,
               facility_decay_weight(near.distance_m),
               near.is_containing
          FROM (
            SELECT h.h3,
                   f.facility_id,
                   ST_Distance(f.geom::geography, h.centroid::geography) AS distance_m,
                   f.h3 IS NOT DISTINCT FROM h.h3 AS is_containing
              FROM hex h
              JOIN facility f
                ON f.coordinate_status = ''ok''
               AND ST_DWithin(f.geom::geography, h.centroid::geography, radius_m)
             WHERE h.h3 = cell
          ) AS near
    ';

COMMENT ON FUNCTION hex_facility_links(h3_cell, double precision) IS
    'Facilities within the interaction radius of one hexagon, decayed. Sections 5 and 8.1.';

-- The same relation over the whole grid, for the scoring step: E3 and F1 through
-- F4 are each one aggregate over this. Written in terms of the single-hexagon
-- function rather than repeating the predicate, so there is one definition of
-- "near" in the database. The lateral join gives the planner an index nested
-- loop, which is what the geography index above is for.
CREATE FUNCTION hex_facility_links_all(radius_m double precision DEFAULT 10000)
    RETURNS SETOF hex_facility_link
    LANGUAGE sql
    STABLE
    PARALLEL SAFE
    AS '
        SELECT link.*
          FROM hex h
          CROSS JOIN LATERAL hex_facility_links(h.h3, radius_m) AS link
    ';

COMMENT ON FUNCTION hex_facility_links_all(double precision) IS
    'The neighbour relation over every hexagon. One aggregate over this is E3 or F1 to F4.';

-- ---- what GET /hex/{h3} renders ------------------------------------------
--
-- The neighbour relation joined out to what the drill-down panel shows: who the
-- facility is, how far away, the public record to check it against, and the
-- compliance and enforcement history behind F2 and F3. Ordered by distance,
-- because that is the order the panel lists them in and sorting a few dozen rows
-- in the database beats shipping them unsorted.
CREATE TYPE hex_facility_detail AS (
    facility_id               text,
    registry_id               text,
    name                      text,
    distance_m                double precision,
    decay_weight              double precision,
    is_containing             boolean,
    is_major_source           boolean,
    has_title_v               boolean,
    is_rcra_lqg               boolean,
    is_rcra_tsdf              boolean,
    geocode_quality           text,
    echo_url                  text,
    quarters_in_noncompliance integer,
    formal_actions            integer,
    penalty_usd               numeric
);

-- actions_since defaults to five years before today, which is the F3 window of
-- section 8.2. It is a parameter because a run scoring last night's data should
-- ask about that night's five years, not about the five years ending whenever
-- somebody opens the panel.
CREATE FUNCTION facilities_near_hex(
        cell h3_cell,
        radius_m double precision DEFAULT 10000,
        actions_since date DEFAULT NULL
    )
    RETURNS SETOF hex_facility_detail
    LANGUAGE sql
    STABLE
    PARALLEL SAFE
    AS '
        SELECT f.facility_id,
               f.registry_id,
               f.name,
               link.distance_m,
               link.decay_weight,
               link.is_containing,
               f.is_major_source,
               f.has_title_v,
               f.is_rcra_lqg,
               f.is_rcra_tsdf,
               f.geocode_quality,
               f.echo_url,
               quarters.noncompliant,
               actions.formal,
               actions.penalties
          FROM hex_facility_links(cell, radius_m) AS link
          JOIN facility f ON f.facility_id = link.facility_id
          LEFT JOIN LATERAL (
              SELECT count(*)::integer AS noncompliant
                FROM facility_compliance_quarter c
               WHERE c.facility_id = f.facility_id
                 AND c.status IN (''violation'', ''high_priority_violation'')
          ) AS quarters ON true
          LEFT JOIN LATERAL (
              SELECT count(*)::integer AS formal,
                     coalesce(sum(a.penalty_usd), 0) AS penalties
                FROM enforcement_action a
               WHERE a.facility_id = f.facility_id
                 AND a.is_formal
                 AND a.settled_on >= coalesce(
                         actions_since, (current_date - interval ''5 years'')::date
                     )
          ) AS actions ON true
         ORDER BY link.distance_m
    ';

COMMENT ON FUNCTION facilities_near_hex(h3_cell, double precision, date) IS
    'The contributing facilities list behind GET /hex/{h3}, nearest first.';
