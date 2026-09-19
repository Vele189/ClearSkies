-- Runs once, on an empty data directory.
-- The postgis image creates postgis itself; the IF NOT EXISTS keeps this idempotent.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS h3;
CREATE EXTENSION IF NOT EXISTS h3_postgis CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;

-- Surfaced by GET /health so a deploy can prove the custom image is the one running.
CREATE OR REPLACE VIEW clearskies_extensions AS
    SELECT extname AS name, extversion AS version
    FROM pg_extension
    WHERE extname IN ('postgis', 'h3', 'h3_postgis', 'vector')
    ORDER BY extname;
