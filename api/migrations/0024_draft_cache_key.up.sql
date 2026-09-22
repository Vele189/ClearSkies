-- 0024: the draft cache key is the request and the run, not just the versions
--
-- Migration 0021 argued that the free-text request should stay out of the key,
-- on the grounds that two people asking for the same document in different
-- words should get the same document. That is true of the phrasing and false of
-- the content. The request is handed to retrieval and to the model: it chooses
-- which statutory passages are pulled and what the draft argues. "Draft a
-- comment letter about the odour complaints" and "draft a comment letter about
-- the flare" produce different documents, and under the old key the first one
-- asked was served to everyone who asked afterwards -- one requester's free
-- text, answered to somebody else.
--
-- So the key gains a SHA-256 of the normalised request. Hashed rather than
-- stored whole because the key is an index and the text is up to 2000
-- characters of somebody's typing; the hash is fixed width, and nothing needs
-- to read the request back.
--
-- The key also gains the scored run. The methodology version was standing in
-- for "which numbers is this draft about", and it cannot: re-running the
-- pipeline under the same methodology produces new scores for the same
-- hexagons, and every cached draft then describes figures the map no longer
-- shows. run_id is the thing that actually changes when the numbers change, and
-- pipeline_run.methodology_version is where the version stamp now comes from.
--
-- Existing rows cannot be given either value. Nothing recorded which request
-- produced them or which run they described, so they are deleted rather than
-- guessed at: the cache costs money to rebuild and nothing else, and a draft
-- attributed to the wrong run is exactly what this migration exists to stop.

DELETE FROM draft;

ALTER TABLE draft
    ADD COLUMN request_sha256 char(64) NOT NULL,
    ADD COLUMN run_id bigint NOT NULL REFERENCES pipeline_run(run_id) ON DELETE CASCADE;

COMMENT ON COLUMN draft.request_sha256 IS
    'SHA-256 of the requester''s free text, whitespace-normalised, with the empty '
    'string hashed when none was given. Part of the cache key: the request steers '
    'retrieval and generation, so a draft answers one request and not any other.';
COMMENT ON COLUMN draft.run_id IS
    'The scored run the draft describes. A new run means new figures for the same '
    'hexagon, which is a different document however the methodology is versioned.';

-- The old unique constraint carries Postgres''s generated name, which depends on
-- how the column list truncates, so it is found rather than spelled out.
DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT conname INTO STRICT constraint_name
      FROM pg_constraint
     WHERE conrelid = 'draft'::regclass AND contype = 'u';
    EXECUTE format('ALTER TABLE draft DROP CONSTRAINT %I', constraint_name);
END
$$;

ALTER TABLE draft
    ADD CONSTRAINT draft_cache_key
    UNIQUE (h3, document_type, run_id, request_sha256,
            methodology_version, corpus_version, prompt_version);

-- draft_lookup_idx indexed the same columns, in the same order, as the unique
-- constraint 0021 declared beside it. A unique constraint is implemented as a
-- unique index, so the lookup already had one and the second was write cost for
-- no read. The constraint above is the index the cache lookup uses.
DROP INDEX IF EXISTS draft_lookup_idx;
