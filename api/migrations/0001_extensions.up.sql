-- 0001: extensions and the H3 cell domain
--
-- infra/postgres/initdb/01-extensions.sql creates the same extensions, but the
-- entrypoint only runs it against an empty data directory. This migration is
-- what makes the extension set reproducible on a database that already has a
-- volume, and it is the authoritative statement of what the project requires.
-- IF NOT EXISTS keeps the two from fighting on a fresh local container.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS h3;
CREATE EXTENSION IF NOT EXISTS h3_postgis CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;

-- Surfaced by GET /health so a deploy can prove the custom image is the one
-- running. Defined here as well as in initdb for the same reason as above.
CREATE OR REPLACE VIEW clearskies_extensions AS
    SELECT extname AS name, extversion AS version
    FROM pg_extension
    WHERE extname IN ('postgis', 'h3', 'h3_postgis', 'vector')
    ORDER BY extname;

-- H3 cells are stored as their 15-character hex string, not as h3-pg's h3index
-- type. The nightly job computes cell indexes in Python and stores them, so
-- nothing in the pipeline may depend on h3-pg being installed; keeping the
-- column type extension-free is what enforces that rather than merely asking
-- for it. The string form is also what GET /hex/{h3} accepts and what the
-- vector tiles carry, so no conversion sits between the table and the API.
--
-- Every mode-1 (cell) H3 index fits in 60 bits, which is exactly 15 hex digits
-- at any resolution, so the length is a real constraint and not a guess.
CREATE DOMAIN h3_cell AS text
    CONSTRAINT h3_cell_is_15_hex_digits CHECK (VALUE ~ '^[0-9a-f]{15}$');

COMMENT ON DOMAIN h3_cell IS
    'H3 cell index as its 15-character hex string. Deliberately not h3-pg''s h3index type.';
