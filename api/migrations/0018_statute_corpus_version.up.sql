-- 0018: version the statute corpus, and make a sealed version immutable (CS-301)
--
-- Migration 0010 built the corpus tables on the assumption that there is one
-- corpus. Appendix B.4 rule 4 says otherwise: the corpus is versioned, it
-- cannot grow at runtime, and adding an authority is a change to the manifest
-- rather than an insert. A single unversioned set of rows cannot express any of
-- that. It also cannot answer the question an audit actually asks, which is not
-- "what does the corpus say" but "what did the corpus say on the day this draft
-- was generated".
--
-- So a version is a first-class row, every document and chunk belongs to one,
-- and sealing is a one-way door enforced in the database.
--
-- Why a trigger rather than a convention. The claim this project makes about
-- the drafting assistant is that it cannot cite anything outside the corpus.
-- That claim is worth exactly as much as the weakest thing standing between a
-- process with a connection string and an INSERT. A comment in the ingestion
-- script is not that. The triggers below are, and they fail the same way for
-- the ingestion script, for psql, and for the API service, which is the point:
-- the API has no business writing here at all, and now it provably cannot.

CREATE TABLE statute_corpus_version (
    version         text        NOT NULL PRIMARY KEY,
    manifest_sha256 text        NOT NULL,
    embedding_model text        NOT NULL,
    built_at        timestamptz NOT NULL DEFAULT now(),
    sealed_at       timestamptz,
    content_sha256  text,
    document_count  integer,
    chunk_count     integer,
    notes           text        NOT NULL DEFAULT '',

    -- Sealing sets all four together or none of them. A version recorded as
    -- sealed without the hash of what was sealed is an audit trail that cannot
    -- be checked, which is worse than no audit trail because it looks like one.
    CONSTRAINT sealed_records_what_it_sealed CHECK (
        (sealed_at IS NULL
         AND content_sha256 IS NULL
         AND document_count IS NULL
         AND chunk_count IS NULL)
        OR
        (sealed_at IS NOT NULL
         AND content_sha256 IS NOT NULL
         AND document_count IS NOT NULL
         AND chunk_count IS NOT NULL)
    )
);

COMMENT ON TABLE statute_corpus_version IS
    'One row per build of the Appendix B corpus. Open while ingesting, sealed once, '
    'never reopened. Drafts record the version they retrieved from.';
COMMENT ON COLUMN statute_corpus_version.manifest_sha256 IS
    'Hash of the Appendix B manifest this version was built from. A manifest change '
    'produces a different version rather than mutating this one, per rule 4.';
COMMENT ON COLUMN statute_corpus_version.content_sha256 IS
    'Hash over every chunk actually ingested, computed at seal. Re-running ingestion '
    'against the same sources must reproduce it; that is what makes the corpus a '
    'checkable artifact rather than whatever happened to be downloaded that day.';
COMMENT ON COLUMN statute_corpus_version.embedding_model IS
    'Recorded because statute_chunk.embedding has a fixed dimension and a corpus '
    'holding vectors from two models returns quietly worse retrievals.';

-- ---- Documents and chunks belong to a version ---------------------------
--
-- 0010 keyed statute_document on document_id alone. Two versions of the corpus
-- both contain 42 U.S.C. 7412, and they are not the same text: an amendment is
-- exactly the case this table exists to keep straight.

ALTER TABLE statute_document
    ADD COLUMN corpus_version text NOT NULL
        REFERENCES statute_corpus_version(version) ON DELETE CASCADE;

ALTER TABLE statute_chunk
    ADD COLUMN corpus_version text NOT NULL;

-- Before the primary key it points at, or Postgres refuses to drop the index
-- backing it.
ALTER TABLE statute_chunk DROP CONSTRAINT statute_chunk_document_id_fkey;

ALTER TABLE statute_document DROP CONSTRAINT statute_document_pkey;
ALTER TABLE statute_document ADD PRIMARY KEY (corpus_version, document_id);

ALTER TABLE statute_chunk
    ADD CONSTRAINT statute_chunk_document_fkey
        FOREIGN KEY (corpus_version, document_id)
        REFERENCES statute_document (corpus_version, document_id) ON DELETE CASCADE;

ALTER TABLE statute_chunk DROP CONSTRAINT statute_chunk_document_id_section_label_ordinal_key;
ALTER TABLE statute_chunk
    ADD CONSTRAINT statute_chunk_citable_unit_key
        UNIQUE (corpus_version, document_id, section_label, ordinal);

-- The verifier's existence check is "is this section in the corpus the draft
-- was generated against", never "is it in some corpus". 0010's index on
-- section_label alone cannot serve that without also scanning other versions.
DROP INDEX statute_chunk_section_idx;
CREATE INDEX statute_chunk_section_idx ON statute_chunk (corpus_version, section_label);

-- ---- Sealing is a one-way door -----------------------------------------

CREATE FUNCTION statute_corpus_version_seal_is_final() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.sealed_at IS NOT NULL THEN
            RAISE EXCEPTION
                'corpus version % is sealed and cannot be deleted', OLD.version
                USING HINT = 'Build a new version. A sealed corpus is what past drafts cite.';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.sealed_at IS NOT NULL THEN
        RAISE EXCEPTION
            'corpus version % was sealed at % and cannot be modified', OLD.version, OLD.sealed_at
            USING HINT = 'Build a new version; see docs/corpus.md.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER statute_corpus_version_seal_is_final
    BEFORE UPDATE OR DELETE ON statute_corpus_version
    FOR EACH ROW EXECUTE FUNCTION statute_corpus_version_seal_is_final();

-- ---- A sealed version's contents cannot change -------------------------
--
-- One function for both tables. Which row supplies the version differs by
-- operation, not by table: an INSERT is checked against the version it is
-- landing in, an UPDATE or DELETE against the version it is already in. An
-- UPDATE that moves a row between versions is refused if either end is sealed,
-- which is the only reading that cannot be used to launder a row out of a
-- sealed corpus.

CREATE FUNCTION statute_corpus_refuse_if_sealed(target text, operation text, relation text)
RETURNS void AS $$
DECLARE
    sealed timestamptz;
BEGIN
    SELECT sealed_at INTO sealed FROM statute_corpus_version WHERE version = target;
    IF sealed IS NOT NULL THEN
        RAISE EXCEPTION
            '% on %: corpus version % is sealed', operation, relation, target
            USING HINT = 'The corpus cannot grow at runtime. Appendix B.4 rule 4.';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION statute_corpus_contents_are_immutable() RETURNS trigger AS $$
BEGIN
    -- Branches are spelled out rather than folded into one expression because
    -- OLD is unassigned in an INSERT trigger and NEW is unassigned in a DELETE
    -- trigger. plpgsql resolves a record reference when it plans the statement,
    -- not when a branch is taken, so naming both in one expression raises
    -- regardless of which operation is running.
    IF TG_OP = 'INSERT' THEN
        PERFORM statute_corpus_refuse_if_sealed(NEW.corpus_version, TG_OP, TG_TABLE_NAME);
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM statute_corpus_refuse_if_sealed(OLD.corpus_version, TG_OP, TG_TABLE_NAME);
        RETURN OLD;
    END IF;

    -- UPDATE. Both ends are checked, so a row cannot be laundered out of a
    -- sealed version by moving it into an open one, or into a sealed version
    -- from an open one.
    PERFORM statute_corpus_refuse_if_sealed(OLD.corpus_version, TG_OP, TG_TABLE_NAME);
    IF NEW.corpus_version IS DISTINCT FROM OLD.corpus_version THEN
        PERFORM statute_corpus_refuse_if_sealed(NEW.corpus_version, TG_OP, TG_TABLE_NAME);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER statute_document_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON statute_document
    FOR EACH ROW EXECUTE FUNCTION statute_corpus_contents_are_immutable();

CREATE TRIGGER statute_chunk_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON statute_chunk
    FOR EACH ROW EXECUTE FUNCTION statute_corpus_contents_are_immutable();

-- ---- The one version anything reads ------------------------------------
--
-- Retrieval (CS-302) and verification (CS-305) both need "the corpus", and
-- both would otherwise have to remember to filter by version and to filter to
-- a sealed one. A view is the cheaper guarantee: forget the filter and you get
-- a syntax error rather than an unsealed draft corpus in production.
--
-- Newest sealed version wins. Sealing is the publish step.

CREATE VIEW statute_corpus_active AS
    SELECT c.corpus_version,
           c.chunk_id,
           c.document_id,
           c.section_label,
           c.ordinal,
           c.text,
           c.embedding,
           d.authority,
           d.citation,
           d.jurisdiction,
           d.edition,
           d.source_url,
           d.retrieved_at,
           d.may_reason_from
      FROM statute_chunk c
      JOIN statute_document d
        ON d.corpus_version = c.corpus_version
       AND d.document_id = c.document_id
     WHERE c.corpus_version = (
               SELECT version FROM statute_corpus_version
                WHERE sealed_at IS NOT NULL
                ORDER BY sealed_at DESC
                LIMIT 1
           );

COMMENT ON VIEW statute_corpus_active IS
    'The sealed corpus the assistant retrieves from and the verifier checks against. '
    'Empty until a version is sealed, which is the correct behaviour: no corpus means '
    'no citations can be verified, so no draft can be produced.';
