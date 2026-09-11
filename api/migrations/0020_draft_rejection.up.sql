-- 0020: the log of drafts the verifier refused, and why (CS-305)
--
-- A draft with an unverifiable citation is rejected and never rendered. That is
-- the right behaviour and it is also, by construction, invisible: the user sees
-- a failure and nobody sees the citation that caused it. Without this table the
-- most important signal the system produces — what the model tried to cite and
-- could not support — would exist only in application logs, which rotate.
--
-- One row per offending citation rather than per draft. A draft rejected for
-- four bad citations is four facts about how the assistant fails, and
-- collapsing them into one row loses three of them. CS-308 reads this to
-- characterise the failure modes, and the model card reports what it found.
--
-- Nothing here is joined to the corpus or to facility by foreign key, on
-- purpose. The whole point of a row in this table is that the citation it
-- records does NOT exist, or does not say what it was claimed to say. A foreign
-- key would make the failing case unrecordable.

CREATE TABLE draft_rejection (
    rejection_id    bigserial   PRIMARY KEY,
    rejected_at     timestamptz NOT NULL DEFAULT now(),

    h3              text        NOT NULL,
    document_type   text        NOT NULL,
    corpus_version  text        NOT NULL,
    prompt_version  text        NOT NULL,
    model           text        NOT NULL,

    -- Which check failed. Free text rather than an enum: the verifier's reasons
    -- will grow, and a migration to add a value to a type is friction that
    -- encourages reusing an existing reason for a new failure.
    reason          text        NOT NULL,

    citation_kind   text        CHECK (citation_kind IN ('statute', 'record')),
    citation_ref    text,
    proposition     text,
    detail          text        NOT NULL DEFAULT ''
);

COMMENT ON TABLE draft_rejection IS
    'Every citation that failed verification, with the draft it came from. The draft '
    'itself was never rendered; this is the only record that it was attempted.';
COMMENT ON COLUMN draft_rejection.citation_ref IS
    'The section label or record id as the model wrote it, verbatim. Not normalised: '
    'a near-miss identifier is evidence about how the model fails and normalising it '
    'away would destroy exactly that.';
COMMENT ON COLUMN draft_rejection.proposition IS
    'What the citation was offered in support of. Null for an existence failure, '
    'where the claim never got as far as being checked against a passage.';

-- The audit reads this by run and by reason. Both are small tables' worth of
-- rows, but "what failed last night" should not scan the history.
CREATE INDEX draft_rejection_recent_idx ON draft_rejection (rejected_at DESC);
CREATE INDEX draft_rejection_reason_idx ON draft_rejection (reason, rejected_at DESC);
