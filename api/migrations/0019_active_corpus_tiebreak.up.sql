-- 0019: make "the active corpus" well defined when two versions tie (CS-302)
--
-- 0018 defined statute_corpus_active as the newest sealed version, ordered by
-- sealed_at alone. That is ambiguous, and the ambiguity sits under the one
-- question the whole drafting assistant depends on: which corpus is a draft
-- being written against.
--
-- Two versions can share a sealed_at. now() is the transaction timestamp, so
-- anything sealing two versions in one transaction gives both the same value,
-- and then the view returns whichever version the planner reaches first. That
-- is not a hypothetical: it is how the corpus tests seed a superseded version
-- alongside a current one, and it would be how a migration or a repair script
-- that resealed a version behaved in production.
--
-- Postgres is entitled to break the tie differently on different runs, on
-- different plans, or after a vacuum. A retrieval layer whose corpus can change
-- between two queries with no write in between is worse than one that reads the
-- wrong corpus consistently, because the second is a bug somebody can find.
--
-- The fix is a total order: sealed_at first, then version as a deterministic
-- tie-break. Nothing about the normal case changes, since versions sealed in
-- separate transactions already differ by timestamp.
--
-- No column changes. This replaces the view definition and nothing else.

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
                ORDER BY sealed_at DESC, version DESC
                LIMIT 1
           );

COMMENT ON VIEW statute_corpus_active IS
    'The sealed corpus the assistant retrieves from and the verifier checks against. '
    'Exactly one version, chosen by a total order so the answer cannot vary between '
    'two queries. Empty until a version is sealed, which is correct: no corpus means '
    'no citations can be verified, so no draft can be produced.';
