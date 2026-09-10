-- 0007: air quality monitors and their daily measurements
--
-- E4 is the only measured indicator in the set, and it is the sparsest.
-- Louisiana has on the order of two dozen regulatory PM2.5 monitors against
-- roughly 150,000 hexes, so most of the state has no value and, per section
-- 8.1, gets no value: never zero, never the state median. An unmonitored parish
-- must not be rewarded for having no sensor.
--
-- The distance to the nearest monitor is also the c_monitor confidence term, so
-- this table is read even for hexes that will never receive an E4 value.

CREATE TABLE monitor (
    monitor_id    text PRIMARY KEY,
    name          text,
    parameter     text NOT NULL,
    geom          geometry(Point, 4326) NOT NULL,
    h3            h3_cell REFERENCES hex(h3),
    is_regulatory boolean NOT NULL DEFAULT false,
    first_seen_on date,
    last_seen_on  date,
    snapshot_id   bigint  NOT NULL REFERENCES source_snapshot(snapshot_id)
);

COMMENT ON COLUMN monitor.monitor_id IS 'OpenAQ location id.';
COMMENT ON COLUMN monitor.is_regulatory IS
    'True for reference-grade regulatory monitors. Low-cost sensors are held but '
    'are not interchangeable with them, and E4 says which it used.';

CREATE INDEX monitor_geom_idx ON monitor USING gist (geom);
CREATE INDEX monitor_parameter_idx ON monitor (parameter);

CREATE TABLE monitor_measurement (
    monitor_id        text NOT NULL REFERENCES monitor(monitor_id) ON DELETE CASCADE,
    parameter         text NOT NULL,
    measured_on       date NOT NULL,
    value             numeric NOT NULL,
    unit              text    NOT NULL,
    observation_count smallint CHECK (observation_count > 0),
    snapshot_id       bigint  NOT NULL REFERENCES source_snapshot(snapshot_id),
    PRIMARY KEY (monitor_id, parameter, measured_on)
);

COMMENT ON TABLE monitor_measurement IS
    'Daily means. E4 is the annual mean of these, so the daily grain is the finest '
    'the indicator can use and the coarsest that still shows a gap in the record.';
COMMENT ON COLUMN monitor_measurement.observation_count IS
    'Hourly observations behind the daily mean. A day built from three hours is not '
    'a day built from twenty-four, and completeness screening needs to see that.';

CREATE INDEX monitor_measurement_date_idx ON monitor_measurement (parameter, measured_on);
