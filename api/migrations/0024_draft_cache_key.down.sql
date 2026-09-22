-- Reverts 0024_draft_cache_key.
--
-- Down migrations exist so a review branch can be unwound locally. Production
-- rolls forward: to undo a shipped migration, write the next one.
--
-- The cache is emptied first. Under the narrower key two rows that differ only
-- by request or by run collide, and reverting is not the moment to choose which
-- of them a hexagon's draft is; the cache costs money to rebuild and nothing
-- else, which is the same argument the up migration makes.

DELETE FROM draft;

ALTER TABLE draft DROP CONSTRAINT draft_cache_key;

ALTER TABLE draft
    DROP COLUMN request_sha256,
    DROP COLUMN run_id;

-- Unnamed, so Postgres regenerates the same default name 0021 relied on.
ALTER TABLE draft
    ADD UNIQUE (h3, document_type, methodology_version, corpus_version, prompt_version);

CREATE INDEX draft_lookup_idx
    ON draft (h3, document_type, methodology_version, corpus_version, prompt_version);
