"""The drafting assistant: schemas, prompts, retrieval and the citation verifier.

Runtime code lives here rather than in the top-level `assistant/` package
because Railway builds the api service with Root Directory /api, so nothing
outside this directory reaches the image. `assistant/` is the offline corpus
build; this is what serves a request. See docs/corpus.md.
"""
