-- Reverts 0012_hex_air_quality.

DROP TABLE IF EXISTS hex_air_quality;

ALTER TABLE monitor DROP COLUMN IF EXISTS openaq_sensor_id;
