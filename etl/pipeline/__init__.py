"""ClearSkies ingestion.

One interface, five sources. What a data source must do is declared in
`pipeline.adapters.base`. What must behave identically across sources — retries,
rate limiting, partial failure, provenance metadata — lives in this package
rather than in the adapters, so adding a sixth source is a contained change.

See etl/README.md for the contract and a walkthrough of adding a source.
"""

__version__ = "0.1.0"
