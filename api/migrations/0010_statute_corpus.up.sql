-- 0010: the statute corpus the drafting assistant retrieves from
--
-- Phase 3 work, created now because it is the only reason pgvector is in the
-- extension set and an extension nothing uses is an extension nobody notices
-- has stopped working.
--
-- Appendix B of the methodology is the manifest, and its rules are structural
-- rather than advisory. The assistant may cite nothing outside this corpus, the
-- corpus cannot grow at runtime, and chunking never crosses a section boundary
-- so a retrieved passage always carries a complete citable unit.

CREATE TABLE statute_document (
    document_id     text NOT NULL PRIMARY KEY,
    authority       text NOT NULL,
    citation        text NOT NULL,
    jurisdiction    text NOT NULL CHECK (jurisdiction IN ('federal', 'louisiana', 'case_law')),
    edition         text NOT NULL,
    source_url      text NOT NULL,
    retrieved_at    timestamptz NOT NULL,
    full_text       text NOT NULL,
    may_reason_from boolean NOT NULL DEFAULT true
);

-- False for the two cases in Appendix B.3. The assistant may cite them for
-- context but may not reason from them to a legal conclusion, and Sandoval is
-- in the corpus specifically so that a Title VI disparate-impact draft gets its
-- procedural posture right: an administrative complaint to EPA, not a lawsuit.
COMMENT ON COLUMN statute_document.may_reason_from IS
    'False for bounded case law. Citable for context, not a basis for a conclusion.';
COMMENT ON COLUMN statute_document.edition IS
    'Edition or amendment date of the text as retrieved, per Appendix B.4 rule 1.';

CREATE TABLE statute_chunk (
    chunk_id      bigserial PRIMARY KEY,
    document_id   text    NOT NULL REFERENCES statute_document(document_id) ON DELETE CASCADE,
    section_label text    NOT NULL,
    ordinal       integer NOT NULL CHECK (ordinal >= 0),
    text          text    NOT NULL,
    embedding     vector(1024),
    UNIQUE (document_id, section_label, ordinal)
);

COMMENT ON COLUMN statute_chunk.section_label IS
    'The citable unit, e.g. ''42 U.S.C. 7412(b)(1)''. Chunking never crosses one.';
COMMENT ON COLUMN statute_chunk.embedding IS
    'Dimension is fixed by the embedding model. Changing models means a migration and '
    'a re-embed, which is the intended friction: a corpus holding vectors from two '
    'models silently returns worse retrievals rather than failing.';

-- Cosine distance, matching how the retrieval query normalises. HNSW rather
-- than IVFFlat because the corpus is small and static, so build time is
-- irrelevant and recall is not.
CREATE INDEX statute_chunk_embedding_idx
    ON statute_chunk USING hnsw (embedding vector_cosine_ops);

-- The citation verifier checks that a cited section exists here and that the
-- proposition appears in the retrieved chunk. Existence alone is not
-- sufficient, so this index supports the first half only.
CREATE INDEX statute_chunk_section_idx ON statute_chunk (section_label);
