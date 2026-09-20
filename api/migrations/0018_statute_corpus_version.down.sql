-- Reverts 0018_statute_corpus_version.
--
-- Returns the corpus tables to the single unversioned set 0010 created. That is
-- only safe because it drops every row: with the version column gone there is
-- no way to say which version a surviving row belonged to, and a corpus whose
-- provenance has been flattened is exactly what the assistant must not cite
-- from. Reverting this migration therefore means re-running ingestion.
--
-- Production rolls forward. This is here so a review branch can be unwound.

DROP VIEW IF EXISTS statute_corpus_active;

DROP TRIGGER IF EXISTS statute_chunk_immutable ON statute_chunk;
DROP TRIGGER IF EXISTS statute_document_immutable ON statute_document;
DROP TRIGGER IF EXISTS statute_corpus_version_seal_is_final ON statute_corpus_version;

DROP FUNCTION IF EXISTS statute_corpus_contents_are_immutable;
DROP FUNCTION IF EXISTS statute_corpus_refuse_if_sealed;
DROP FUNCTION IF EXISTS statute_corpus_version_seal_is_final;

DELETE FROM statute_chunk;
DELETE FROM statute_document;

ALTER TABLE statute_chunk DROP CONSTRAINT IF EXISTS statute_chunk_citable_unit_key;
ALTER TABLE statute_chunk DROP CONSTRAINT IF EXISTS statute_chunk_document_fkey;
ALTER TABLE statute_chunk DROP COLUMN IF EXISTS corpus_version;

-- The single-column primary key has to be back before anything can reference
-- it, so the document side is rebuilt first and the chunk foreign key last.
ALTER TABLE statute_document DROP CONSTRAINT IF EXISTS statute_document_pkey;
ALTER TABLE statute_document DROP COLUMN IF EXISTS corpus_version;
ALTER TABLE statute_document ADD PRIMARY KEY (document_id);

ALTER TABLE statute_chunk
    ADD CONSTRAINT statute_chunk_document_id_fkey
        FOREIGN KEY (document_id) REFERENCES statute_document(document_id) ON DELETE CASCADE;

ALTER TABLE statute_chunk
    ADD CONSTRAINT statute_chunk_document_id_section_label_ordinal_key
        UNIQUE (document_id, section_label, ordinal);

DROP INDEX IF EXISTS statute_chunk_section_idx;
CREATE INDEX statute_chunk_section_idx ON statute_chunk (section_label);

DROP TABLE IF EXISTS statute_corpus_version;
