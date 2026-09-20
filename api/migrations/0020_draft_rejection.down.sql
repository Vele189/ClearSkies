-- Reverts 0020_draft_rejection.
--
-- Drops the audit log of refused citations. Production rolls forward; this
-- exists so a review branch can be unwound.

DROP TABLE IF EXISTS draft_rejection;
