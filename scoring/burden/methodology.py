"""The methodology version, restated from the registry of record.

`api/app/methodology.py` declares it. This package cannot import that module,
for the same reason it cannot import the indicator registry: `api` and `scoring`
are separate distributions with separate dependency sets, and this one has none.
`tests/test_methodology.py` reads the API module off disk and fails if the two
disagree, which is the arrangement `indicators.py` already uses.

Why it matters here rather than only in the API. Section 17 says every published
score carries the version that produced it, and section 13 requires a run to be
reproducible from its inputs and that version together. A run stamped with a
version whose rules it was not produced under cannot be reproduced by anyone
reading the paper at that version, which is the one promise the audit trail
makes.
"""

# Kept equal to `api/app/methodology.py`, which is in turn checked against the
# changelog in docs/methodology.md section 18.
METHODOLOGY_VERSION = "0.1.3"
