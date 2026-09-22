-- 0026: TRUNCATE cannot empty a sealed corpus either (AUD-12)
--
-- Migration 0018 makes a sealed corpus version immutable with row-level
-- triggers, and row-level triggers do not fire for TRUNCATE. Postgres empties
-- the table without visiting a row, so `TRUNCATE statute_chunk` removed every
-- chunk of every sealed version while the version rows went on recording the
-- hash and the counts of text that was no longer there. The one-way door had a
-- second exit that nobody had tested.
--
-- A statement-level trigger is the only hook TRUNCATE has, and it sees no rows,
-- so it cannot refuse per version the way 0018 does. It refuses whenever any
-- version is sealed. That is the right granularity anyway: TRUNCATE cannot be
-- limited to one version, so a TRUNCATE on a database holding a sealed corpus
-- is always a TRUNCATE of that corpus. An open version is still cleared the way
-- `corpus.store.write` clears it, with a DELETE the row triggers can judge.
--
-- All three tables 0018 protects get the guard. TRUNCATE ... CASCADE fires the
-- triggers of every table it reaches, so truncating the version table or the
-- document table cannot empty the chunks by the back door.

CREATE FUNCTION statute_corpus_refuse_truncate() RETURNS trigger AS $$
DECLARE
    sealed text;
BEGIN
    SELECT version INTO sealed FROM statute_corpus_version
     WHERE sealed_at IS NOT NULL
     ORDER BY sealed_at
     LIMIT 1;
    IF sealed IS NOT NULL THEN
        RAISE EXCEPTION
            'TRUNCATE on %: corpus version % is sealed', TG_TABLE_NAME, sealed
            USING HINT = 'A sealed corpus is what past drafts cite. Build a new version instead.';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER statute_corpus_version_refuse_truncate
    BEFORE TRUNCATE ON statute_corpus_version
    FOR EACH STATEMENT EXECUTE FUNCTION statute_corpus_refuse_truncate();

CREATE TRIGGER statute_document_refuse_truncate
    BEFORE TRUNCATE ON statute_document
    FOR EACH STATEMENT EXECUTE FUNCTION statute_corpus_refuse_truncate();

CREATE TRIGGER statute_chunk_refuse_truncate
    BEFORE TRUNCATE ON statute_chunk
    FOR EACH STATEMENT EXECUTE FUNCTION statute_corpus_refuse_truncate();
