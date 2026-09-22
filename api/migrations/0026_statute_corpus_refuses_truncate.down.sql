-- Reverts 0026_statute_corpus_refuses_truncate.
--
-- Reopens the TRUNCATE path around 0018's row triggers. Production rolls
-- forward; this is here so a review branch can be unwound.

DROP TRIGGER IF EXISTS statute_chunk_refuse_truncate ON statute_chunk;
DROP TRIGGER IF EXISTS statute_document_refuse_truncate ON statute_document;
DROP TRIGGER IF EXISTS statute_corpus_version_refuse_truncate ON statute_corpus_version;

DROP FUNCTION IF EXISTS statute_corpus_refuse_truncate;
