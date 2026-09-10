-- 0003: census geography, the hex grid, and the crosswalk between them
--
-- Methodology section 7 moves three of the five sources from tracts to
-- hexagons through 2020 block populations. The crosswalk that step produces is
-- expensive to compute and is read by every tract-sourced indicator, so it is
-- a table rather than a query: tract_hex_weight is the interpolation, stored.

CREATE TABLE census_tract (
    geoid       char(11) PRIMARY KEY,
    state_fips  char(2)  NOT NULL,
    county_fips char(3)  NOT NULL,
    name        text,
    geom        geometry(MultiPolygon, 4326) NOT NULL,
    aland_m2    bigint,
    awater_m2   bigint,
    tiger_year  smallint NOT NULL,
    snapshot_id bigint   NOT NULL REFERENCES source_snapshot(snapshot_id)
);

COMMENT ON COLUMN census_tract.geoid IS 'State, county and tract FIPS concatenated.';

CREATE INDEX census_tract_geom_idx ON census_tract USING gist (geom);
CREATE INDEX census_tract_county_idx ON census_tract (state_fips, county_fips);

-- The ancillary layer of section 7. Block populations are 2020 Decennial
-- PL 94-171 counts, not estimates, which is the whole reason they are trusted
-- to distribute tract values.
CREATE TABLE census_block (
    geoid       char(15) PRIMARY KEY,
    tract_geoid char(11) NOT NULL REFERENCES census_tract(geoid) ON DELETE CASCADE,
    geom        geometry(MultiPolygon, 4326) NOT NULL,
    population  integer  NOT NULL CHECK (population >= 0),
    aland_m2    bigint,
    snapshot_id bigint   NOT NULL REFERENCES source_snapshot(snapshot_id)
);

COMMENT ON COLUMN census_block.population IS
    '2020 Decennial PL 94-171 count. A count, not an ACS estimate.';

CREATE INDEX census_block_geom_idx ON census_block USING gist (geom);
CREATE INDEX census_block_tract_idx ON census_block (tract_geoid);

CREATE TABLE hex (
    h3             h3_cell  PRIMARY KEY,
    resolution     smallint NOT NULL DEFAULT 8 CHECK (resolution = 8),
    centroid       geometry(Point, 4326)   NOT NULL,
    boundary       geometry(Polygon, 4326) NOT NULL,
    state_fips     char(2)  NOT NULL,
    county_fips    char(3),
    parish_name    text,
    in_pilot_state boolean  NOT NULL,
    land_fraction  numeric(5, 4) CHECK (land_fraction BETWEEN 0 AND 1)
);

-- Resolution 8 is fixed by methodology section 5, and the check says so rather
-- than leaving a mixed-resolution grid as something a bad load could produce.
-- Serving another resolution is a methodology revision, so it should also be a
-- migration.
COMMENT ON COLUMN hex.resolution IS 'Fixed at 8 by methodology section 5.';
COMMENT ON COLUMN hex.in_pilot_state IS
    'Centroid falls inside the state boundary. Percentile denominators use only these.';
COMMENT ON COLUMN hex.land_fraction IS
    'Share of the cell over land. The grid extends over coastal water to the state line.';

CREATE INDEX hex_centroid_idx ON hex USING gist (centroid);
CREATE INDEX hex_boundary_idx ON hex USING gist (boundary);
CREATE INDEX hex_county_idx ON hex (state_fips, county_fips);
CREATE INDEX hex_pilot_idx ON hex (h3) WHERE in_pilot_state;

-- The result of section 7 steps 1 and 2, one row per tract-hex overlap.
--
-- Extensive quantities multiply through pop_weight; intensive ones are
-- averaged over population, which is what the population column is for. Both
-- formulas in section 7 are one join against this table.
CREATE TABLE tract_hex_weight (
    tract_geoid        char(11) NOT NULL REFERENCES census_tract(geoid) ON DELETE CASCADE,
    h3                 h3_cell  NOT NULL REFERENCES hex(h3) ON DELETE CASCADE,
    population         numeric  NOT NULL CHECK (population >= 0),
    pop_weight         numeric  NOT NULL CHECK (pop_weight > 0 AND pop_weight <= 1),
    area_weight        numeric  NOT NULL CHECK (area_weight > 0 AND area_weight <= 1),
    block_count        integer  NOT NULL CHECK (block_count > 0),
    mean_block_area_m2 numeric,
    PRIMARY KEY (tract_geoid, h3)
);

COMMENT ON COLUMN tract_hex_weight.population IS
    'P(t n h): block-apportioned population of the overlap, the weight for intensive values.';
COMMENT ON COLUMN tract_hex_weight.pop_weight IS
    'Share of the tract''s population falling in this hex, the weight for extensive values.';
COMMENT ON COLUMN tract_hex_weight.mean_block_area_m2 IS
    'Mean source block area. Large blocks are where the uniformity assumption of section 7 '
    'is weakest, so this feeds the c_spatial confidence term.';

CREATE INDEX tract_hex_weight_h3_idx ON tract_hex_weight (h3);
