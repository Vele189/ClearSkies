-- 0011: measured air quality as each hex sees it, including the hexes that see none
--
-- 0007 holds the monitors and their daily means at their native geography. This
-- is the other half of E4: what a hex can say about measured PM2.5, which for
-- most of Louisiana is nothing at all.
--
-- The row exists precisely so that "nothing" is a stored fact rather than an
-- absent one. Methodology section 8.1 gives a hex beyond 25 km of a monitor no
-- E4 value, never zero and never the state median, and section 11 forbids
-- coercing one into the other. A hex with no value still carries the distance to
-- the nearest monitor, because that distance is the c_monitor confidence term of
-- section 12, min(1, 10 km / d_nearest), and the detail panel displays it.
--
-- Not keyed by run. The monitor network and its readings are facts about a
-- snapshot of OpenAQ, not about a scoring pass, so this is a source table like
-- the others in 0004 to 0008 and carries a snapshot_id. The nightly pull upserts
-- on (h3, parameter).

-- One OpenAQ location can hold several PM2.5 sensors, and monitor_measurement is
-- keyed by monitor rather than by sensor. The adapter reads one series per
-- location and records which, so a stored daily mean can be walked back to the
-- instrument that produced it.
ALTER TABLE monitor ADD COLUMN openaq_sensor_id text;

COMMENT ON COLUMN monitor.openaq_sensor_id IS
    'The OpenAQ sensor whose series was read. A location with several PM2.5 sensors '
    'is read through the most recently reporting one; averaging instruments would be '
    'a methodology choice section 8.1 does not make.';

CREATE TABLE hex_air_quality (
    h3                 h3_cell NOT NULL,
    parameter          text    NOT NULL,
    window_start       date    NOT NULL,
    window_end         date    NOT NULL,
    value              numeric CHECK (value >= 0),
    observed           boolean NOT NULL,
    unit               text,
    nearest_monitor_id text    NOT NULL REFERENCES monitor(monitor_id) ON DELETE CASCADE,
    nearest_monitor_km numeric NOT NULL CHECK (nearest_monitor_km >= 0),
    monitors_used      smallint NOT NULL DEFAULT 0 CHECK (monitors_used >= 0),
    day_count          integer  NOT NULL DEFAULT 0 CHECK (day_count >= 0),
    observation_count  integer  NOT NULL DEFAULT 0 CHECK (observation_count >= 0),
    latest_measured_on date,
    snapshot_id        bigint  NOT NULL REFERENCES source_snapshot(snapshot_id),
    PRIMARY KEY (h3, parameter),
    -- The same shape as hex_indicator's constraint, and for the same reason.
    -- Zero is an observation and NULL is an absence; only the incoherent
    -- direction is forbidden, an unobserved hex that somehow carries a value.
    CONSTRAINT hex_air_quality_absent_has_no_value CHECK (observed OR value IS NULL),
    -- An observed value came from at least one monitor and at least one day. A
    -- row claiming a measurement with nothing behind it is a loader bug.
    CONSTRAINT hex_air_quality_observed_has_support
        CHECK (NOT observed OR (monitors_used > 0 AND day_count > 0)),
    CONSTRAINT hex_air_quality_window_ordered CHECK (window_start <= window_end)
);

COMMENT ON TABLE hex_air_quality IS
    'One row per hex per pollutant: the interpolated annual mean where there is one, '
    'and the distance to the nearest monitor whether or not there is.';

-- Deliberately no foreign key to hex. The adapter computes coverage from monitor
-- geometry over a bounding envelope, which is wider than the state boundary the
-- CS-007 grid is built from, so a few rows describe cells the grid does not
-- contain. Every read joins hex to this table rather than the reverse, so those
-- rows are inert; an FK would instead make the pull fail on cells nobody asks
-- about.
COMMENT ON COLUMN hex_air_quality.h3 IS
    'Resolution 8 cell. Not an FK: coverage is computed over an envelope wider than '
    'the pilot grid, and the extra cells are never joined to.';

COMMENT ON COLUMN hex_air_quality.value IS
    'E4 before percentile ranking: the inverse-distance weighted annual mean of the '
    'monitors within 25 km. NULL where there are none, which is most of Louisiana.';
COMMENT ON COLUMN hex_air_quality.observed IS
    'False means unmeasured, not clean. Section 8.1: an unmonitored parish must not '
    'be rewarded for having no sensor.';
COMMENT ON COLUMN hex_air_quality.nearest_monitor_km IS
    'Great-circle distance to the nearest monitor that reported in the window. The '
    'c_monitor term of section 12 is min(1, 10 / this), and the panel shows it.';
COMMENT ON COLUMN hex_air_quality.monitors_used IS
    'Monitors that contributed to the interpolation. Zero where the value is absent.';
COMMENT ON COLUMN hex_air_quality.day_count IS
    'Monitor-days behind the value. Two monitors contributing 300 days each is 600.';
COMMENT ON COLUMN hex_air_quality.observation_count IS
    'Hourly observations behind those days. A year built from three hours a day is '
    'not a year built from twenty-four, and the confidence terms need to see that.';
COMMENT ON COLUMN hex_air_quality.latest_measured_on IS
    'Most recent day behind the value. Recency at the grain a reader asks about: a '
    'monitor that stopped reporting in March is visible here in November.';
COMMENT ON COLUMN hex_air_quality.window_end IS
    'Last day of the trailing year the mean covers. The vintage_end for E4.';

-- The two read paths: one hex for the detail panel, which the primary key
-- already serves, and the whole covered set for a scoring pass.
CREATE INDEX hex_air_quality_observed_idx ON hex_air_quality (parameter) WHERE observed;
CREATE INDEX hex_air_quality_monitor_idx ON hex_air_quality (nearest_monitor_id);
