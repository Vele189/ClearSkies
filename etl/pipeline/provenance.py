"""Where every number came from, kept per pull and rendered as a page.

`PullMetadata` already carries the whole answer: the release a pull read, when it
ran, how many records reached the database, what it is known not to cover, and
the checksum of every file it downloaded. CS-110 is not about collecting that. It
is about the two ways it was still being lost.

**It only existed for the latest run.** The manifest was written beside the
night's quality report and the next night overwrote the directory. But the
question the provenance page answers is "where did this number come from", and a
reader checking a claim from a month ago needs the manifest from a month ago, not
tonight's. So every pull appends to a history that outlives the run that wrote
it, and `rows_for_sql` emits the exact shapes migration 0012's three tables take,
kept beside the model they mirror so the two cannot drift.

**The page was written by hand.** `docs/provenance.md` had a generated block with
nothing generating it. A hand-maintained provenance page is a provenance page
that stops matching the data, usually in the direction that flatters it, so the
block is rewritten from the manifests by the nightly job and the markers are
the only part a person touches.

One rule runs through all of it: a failed pull is published too. A provenance
page that quietly omits the night a source could not be reached is telling the
reader the data is more complete than it is, and `status` is on the page for
exactly that reason.
"""

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.metadata import PullMetadata

HISTORY = "provenance.jsonl"

# The block in docs/provenance.md that this module owns. Everything outside the
# markers is prose a person wrote and the generator must not touch.
BEGIN = "<!-- BEGIN GENERATED PROVENANCE -->"
END = "<!-- END GENERATED PROVENANCE -->"

HEADER = (
    "| Source | Vintage | Pulled | Records | Status | Checksum | Known gaps |\n"
    "|---|---|---|---|---|---|---|"
)

EMPTY_NOTE = (
    "_No pipeline run has happened yet. Phase 1 wires the five adapters into the\n"
    "nightly job and this table fills itself in._"
)


class ProvenanceStore:
    """Every pull this pipeline has made, appended, oldest first.

    A file rather than a database for the same reason the run ledger is one: the
    nightly job has to be able to record where its data came from on a night the
    database was the thing that broke. The durable home is migration 0012, and
    `rows_for_sql` is the payload the Postgres sink will insert.

    Append-only. The value of the file is that it is longer than the run that
    wrote it; a store that keeps only the latest pull per source cannot answer
    the question the page exists to answer.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def record(self, manifests: Sequence[PullMetadata], *, run_id: str | None = None) -> None:
        if not manifests:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / HISTORY).open("a", encoding="utf-8") as handle:
            for manifest in manifests:
                row = manifest.model_dump(mode="json")
                row["run_id"] = run_id
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    def history(self, source: str | None = None) -> list[PullMetadata]:
        """Every pull, oldest first, optionally narrowed to one source."""
        path = self.root / HISTORY
        if not path.exists():
            return []
        pulls = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            row.pop("run_id", None)
            pulls.append(PullMetadata.model_validate(row))
        if source is None:
            return pulls
        return [p for p in pulls if p.source == source]

    def run_ids(self) -> list[str | None]:
        """The run each recorded pull belonged to, in the same order as `history`."""
        path = self.root / HISTORY
        if not path.exists():
            return []
        return [
            json.loads(line).get("run_id")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def latest(self) -> list[PullMetadata]:
        """The most recent pull of each source, sorted by source name."""
        return latest_per_source(self.history())


def latest_per_source(pulls: Iterable[PullMetadata]) -> list[PullMetadata]:
    """One pull per source, the newest.

    A failed pull can be the newest, and when it is, it is what the page shows.
    Falling back to the last pull that went well would publish a row implying the
    source is current when tonight it could not be read at all.
    """
    newest: dict[str, PullMetadata] = {}
    for pull in pulls:
        held = newest.get(pull.source)
        if held is None or pull.pulled_at >= held.pulled_at:
            newest[pull.source] = pull
    return [newest[name] for name in sorted(newest)]


# ---- the page ----------------------------------------------------------


def render_block(pulls: Sequence[PullMetadata]) -> str:
    """The generated block's contents: a header, a row per source, or a note.

    `PullMetadata.provenance_row()` renders each row. It lives on the model
    rather than here so that the page and anything else that displays a pull
    agree about what a pull looks like without being wired together.
    """
    if not pulls:
        return f"{HEADER}\n\n{EMPTY_NOTE}"
    rows = "\n".join(pull.provenance_row() for pull in pulls)
    return f"{HEADER}\n{rows}"


def update_page(text: str, pulls: Sequence[PullMetadata]) -> str:
    """Replace the generated block in the page, leaving every other line alone.

    Raises if the markers are missing rather than appending a table somewhere
    plausible. A generator that silently invents a place to write is one that
    quietly duplicates the table the first time somebody reformats the page.
    """
    start = text.find(BEGIN)
    end = text.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"the page has no generated block; expected {BEGIN!r} and {END!r} in that order"
        )
    head = text[: start + len(BEGIN)]
    tail = text[end:]
    return f"{head}\n\n{render_block(pulls)}\n\n{tail}"


def write_page(path: Path, pulls: Sequence[PullMetadata]) -> bool:
    """Rewrite the page's generated block. Returns whether the file changed.

    The return value is what lets the nightly job commit only when there is
    something to commit, rather than producing an empty commit every night.
    """
    before = path.read_text(encoding="utf-8")
    after = update_page(before, pulls)
    if after == before:
        return False
    path.write_text(after, encoding="utf-8")
    return True


# ---- the shapes the database will take ---------------------------------


def rows_for_sql(manifest: PullMetadata, *, run_id: str | None = None) -> dict[str, Any]:
    """One manifest as the three rows migration 0012 stores it in.

    Returned together rather than as three functions because they are inserted
    together: the gaps and the artifacts are meaningless without the pull they
    hang off, and the pull_id that joins them is assigned by the insert.
    """
    return {
        "source_pull": {
            "run_id": run_id,
            "source": manifest.source,
            "source_title": manifest.source_title,
            "vintage": manifest.vintage,
            "pulled_at": manifest.pulled_at.isoformat(),
            "status": manifest.status,
            "records_fetched": manifest.counts.fetched,
            "records_validated": manifest.counts.validated,
            "records_rejected": manifest.counts.rejected,
            "records_normalized": manifest.counts.normalized,
            "records_loaded": manifest.counts.loaded,
            "rejection_reasons": dict(manifest.rejection_reasons),
            "duration_s": manifest.duration_s,
            "notes": list(manifest.notes),
        },
        "source_pull_gap": [
            {
                "scope": gap.scope,
                "detail": gap.detail,
                "affects": list(gap.affects),
                "since": gap.since.isoformat() if gap.since else None,
            }
            for gap in manifest.known_gaps
        ],
        "source_pull_artifact": [
            {
                "url": artifact.url,
                "retrieved_at": artifact.retrieved_at.isoformat(),
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "media_type": artifact.media_type,
                "from_snapshot": artifact.from_snapshot,
            }
            for artifact in manifest.artifacts
        ],
    }


def payload(pulls: Sequence[PullMetadata]) -> dict[str, Any]:
    """What the API publishes, and what CS-406 renders.

    The same fields as the page, in the same order, because a reader who checks
    the page against the endpoint should not have to reconcile two accounts of
    one pull.
    """
    return {
        "sources": [
            {
                "source": pull.source,
                "title": pull.source_title,
                "vintage": pull.vintage,
                "pulled_at": pull.pulled_at.isoformat(),
                "status": pull.status,
                "records": pull.record_count,
                "rejected": pull.counts.rejected,
                "artifacts": [
                    {
                        "url": a.url,
                        "sha256": a.sha256,
                        "short_sha": a.short_sha,
                        "retrieved_at": a.retrieved_at.isoformat(),
                        "from_snapshot": a.from_snapshot,
                    }
                    for a in pull.artifacts
                ],
                "known_gaps": [
                    {
                        "scope": g.scope,
                        "detail": g.detail,
                        "affects": list(g.affects),
                        "since": g.since.isoformat() if g.since else None,
                    }
                    for g in pull.known_gaps
                ],
                "notes": list(pull.notes),
            }
            for pull in pulls
        ],
    }


def summarise(pulls: Sequence[PullMetadata], *, now: datetime | None = None) -> str:
    """One line per source, for the terminal."""
    if not pulls:
        return "no pulls recorded yet"
    lines = []
    for pull in pulls:
        age = ""
        if now is not None:
            days = (now - pull.pulled_at).total_seconds() / 86_400
            age = f", {days:.1f} days ago"
        lines.append(
            f"{pull.source:14} {pull.vintage:16} {pull.status:8} "
            f"{pull.record_count:>9} records{age}"
        )
    return "\n".join(lines)


__all__ = [
    "BEGIN",
    "END",
    "HISTORY",
    "ProvenanceStore",
    "latest_per_source",
    "payload",
    "render_block",
    "rows_for_sql",
    "summarise",
    "update_page",
    "write_page",
]
