-- Reverts 0019_active_corpus_tiebreak.
--
-- Restores 0018's view definition exactly, ambiguous ordering included. Down
-- migrations exist so a review branch can be unwound to a known state, and the
-- known state here is the one 0018 left behind.

CREATE OR REPLACE VIEW statute_corpus_active AS
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
