"""Constants that belong to docs/methodology.md as a whole.

`indicators.py` is the registry of record for section 8. This module is for the
values that are properties of the paper rather than of one section of it,
beginning with its version.

Section 17 makes that version load-bearing rather than decorative. Every
published score carries the version that produced it, and historical scores are
not silently recomputed under a new one, so a score stamped 0.1.0 that was in
fact produced under 0.1.2's rules is an audit trail that lies about itself. The
constant below is therefore checked against the changelog in the document it
names: `tests/test_methodology.py` reads section 18 and fails if the newest
entry there is not this string. That check exists because the two had already
drifted once, with the paper at 0.1.2 and `/indicators` still answering 0.1.0.
"""

# The newest entry in docs/methodology.md section 18. Bumping the paper without
# bumping this is a failing test, not a stale endpoint.
METHODOLOGY_VERSION = "0.1.3"
