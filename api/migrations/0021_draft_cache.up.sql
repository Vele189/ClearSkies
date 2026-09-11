-- 0021: the draft cache, and the record of what generation cost (CS-306)
--
-- Two tables with one purpose between them: a bill nobody is watching is the
-- way this project stops being free to run.
--
-- The cache key is the whole reason this is a table rather than a dictionary.
-- A draft is a function of the hexagon, the document type, and the three
-- versions that decide what it says: the methodology that produced the score,
-- the corpus the citations came from, and the prompt that set the rules. Change
-- any of those and the cached draft is an answer to a different question. Key
-- on all of them and a revision invalidates exactly what it should, with no
-- invalidation step to remember and no stale draft served under a new
-- methodology version.
--
-- What is NOT keyed on is the user's free-text request. Two people asking for a
-- comment letter on the same hexagon in different words should get the same
-- document, because the document is about the hexagon and not about the
-- phrasing. Keying on the request would make the cache almost always miss,
-- which is the same as not having one.

CREATE TABLE draft (
    draft_id            bigserial   PRIMARY KEY,

    h3                  text        NOT NULL,
    document_type       text        NOT NULL,
    methodology_version text        NOT NULL,
    corpus_version      text        NOT NULL,
    prompt_version      text        NOT NULL,

    model               text        NOT NULL,
    confidence_band     text        NOT NULL CHECK (confidence_band IN ('high', 'moderate', 'low')),
    document            jsonb       NOT NULL,

    generated_at        timestamptz NOT NULL DEFAULT now(),
    request_tokens      integer     NOT NULL DEFAULT 0,
    response_tokens     integer     NOT NULL DEFAULT 0,

    UNIQUE (h3, document_type, methodology_version, corpus_version, prompt_version)
);

COMMENT ON TABLE draft IS
    'Cached drafts that passed citation verification. Nothing that failed CS-305 is '
    'ever written here: the cache holds documents fit to show, so a cache hit needs '
    'no re-verification.';
COMMENT ON COLUMN draft.confidence_band IS
    'The insufficient band is absent by constraint. A hexagon the pipeline does not '
    'trust cannot be drafted from, so a cached draft for one is unrepresentable.';

-- The cache lookup, and the only query the endpoint runs on a hit.
CREATE INDEX draft_lookup_idx
    ON draft (h3, document_type, methodology_version, corpus_version, prompt_version);


-- ---- What every call cost ---------------------------------------------
--
-- Separate from the cache on purpose. The cache holds what succeeded; this
-- holds every attempt, including the ones that were refused, rejected by the
-- verifier, or failed at the provider. Cost is incurred by attempts, not by
-- successes, and a usage table that only recorded successes would understate
-- the bill by exactly the amount worth worrying about.

CREATE TABLE llm_usage (
    usage_id        bigserial   PRIMARY KEY,
    called_at       timestamptz NOT NULL DEFAULT now(),

    purpose         text        NOT NULL,
    model           text        NOT NULL,
    h3              text,
    document_type   text,

    request_tokens  integer     NOT NULL DEFAULT 0,
    response_tokens integer     NOT NULL DEFAULT 0,
    usd             numeric(10, 6) NOT NULL DEFAULT 0,

    outcome         text        NOT NULL,
    detail          text        NOT NULL DEFAULT ''
);

COMMENT ON COLUMN llm_usage.purpose IS
    'Which call this was: generation, verification, or embedding. Verification runs '
    'a second model over every citation, and a cost report that attributed all of it '
    'to generation would mislead about where the money goes.';
COMMENT ON COLUMN llm_usage.usd IS
    'Estimated from the token counts and a price table in the application. Indicative '
    'only: the provider''s invoice is the truth, and the hard cap lives with the '
    'provider for exactly that reason.';
COMMENT ON COLUMN llm_usage.outcome IS
    'served, refused, unverifiable, provider_error, or cached. Cost is incurred by '
    'attempts and not by successes.';

-- The month-to-date question is "everything since the first of the month", a
-- range over called_at with purpose as the second key. Not an index on
-- date_trunc('month', called_at): that function is STABLE rather than
-- IMMUTABLE over timestamptz, because its answer depends on the session time
-- zone, and Postgres refuses to index it. A range scan answers the same
-- question and does not silently bake one time zone into the index.
CREATE INDEX llm_usage_recent_idx ON llm_usage (called_at DESC);
CREATE INDEX llm_usage_spend_idx ON llm_usage (called_at, purpose);
