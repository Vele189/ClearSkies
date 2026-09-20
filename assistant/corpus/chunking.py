"""Split sections into retrievable chunks without crossing a section boundary.

Appendix B rule 2, and it is a retrieval rule rather than a storage one. A chunk
is what retrieval hands the model and what the verifier checks a proposition
against. If a chunk spanned the end of § 7412 and the start of § 7413, the model
would be shown two authorities under one label, and whichever it used the
citation would be half wrong in a way no existence check could catch. The
section boundary is therefore hard: never crossed, in either direction,
whatever it does to chunk sizes.

Inside a section, the label is chosen rather than assumed. A chunk is labelled
with the **deepest subdivision that contains all of it**. A chunk holding only
the text of § 7412(a)(1) is labelled § 7412(a)(1); one holding (a)(1) through
(a)(6) is labelled § 7412(a), because that is the smallest unit that honestly
covers it; one spanning (a) and (b) is labelled § 7412.

That rule is the whole design. The alternative, labelling a chunk with the first
marker in it, produces citations that name a subdivision the quoted text is only
partly inside, and a verifier checking existence would wave them through. Here a
label is never narrower than the text it covers, so a citation the assistant
copies off a chunk is a citation that actually contains the proposition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from corpus.parse import Block, Section

# Roughly 1,500 tokens of legal English. The embedding model takes far more, but
# a chunk that is most of a page retrieves as a vague average of everything in
# it; the limit is about retrieval precision, not the model's input size.
# Characters rather than tokens so chunking needs no tokenizer and produces the
# same result on any machine.
TARGET_CHARS = 6_000

# Below this, a trailing fragment is folded back rather than standing alone. A
# 200-character chunk embeds to a point near everything and useful for nothing.
MIN_CHARS = 400


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage, and the citation it carries."""

    section_label: str
    ordinal: int
    text: str


def _paths(blocks: tuple[Block, ...]) -> list[tuple[str, ...]]:
    """The subdivision path of each block, e.g. ("a", "1") for § 7412(a)(1)."""
    out: list[tuple[str, ...]] = []
    stack: list[str] = []
    for block in blocks:
        if block.marker is not None:
            del stack[block.depth :]
            while len(stack) < block.depth:
                # A marker deeper than anything open above it. Rare, and the
                # honest reading is that the levels between are unlabelled.
                stack.append("")
            # An uncitable marker occupies its level so the nesting stays right,
            # but contributes nothing a citation can name. `_common` stops at
            # the first empty element, so a chunk under one is cited against the
            # nearest subdivision the publisher actually marked.
            stack.append(block.marker if block.citable else "")
        out.append(tuple(stack))
    return out


def _common(paths: list[tuple[str, ...]]) -> tuple[str, ...]:
    """The deepest path prefix shared by every block in a chunk."""
    if not paths:
        return ()
    shared = paths[0]
    for path in paths[1:]:
        limit = min(len(shared), len(path))
        cut = limit
        for i in range(limit):
            if shared[i] != path[i]:
                cut = i
                break
        shared = shared[:cut]
        if not shared:
            break
    # An empty element means a level nothing labelled, which cannot appear in a
    # citation, so the path stops there.
    if "" in shared:
        shared = shared[: shared.index("")]
    return shared


def _label(citation_base: str, path: tuple[str, ...]) -> str:
    return citation_base + "".join(f"({part})" for part in path)


def _units(blocks: tuple[Block, ...], indices: list[int], depth: int) -> list[list[int]]:
    """Split a run of blocks at the boundaries of subdivisions at `depth`.

    Any blocks before the first marker at that depth form their own run: the
    flush text at the top of a subsection belongs to the subsection, not to its
    first paragraph.
    """
    units: list[list[int]] = []
    for i in indices:
        block = blocks[i]
        starts_unit = block.marker is not None and block.depth == depth
        if starts_unit or not units:
            units.append([i])
        else:
            units[-1].append(i)
    return units


def _group(
    blocks: tuple[Block, ...],
    paths: list[tuple[str, ...]],
    depth: int,
    budget: int,
    min_chars: int,
    indices: list[int] | None = None,
) -> list[list[int]]:
    """Group blocks into chunks along subdivision boundaries.

    Structure first, size second. A subdivision that fits becomes one chunk and
    keeps its own label; one that does not is split at the next level down, and
    so on until the blocks themselves are the unit. Only then does size force a
    split that structure did not ask for.

    Packing greedily by size instead would be simpler and would label almost
    everything with the bare section number: a chunk that happens to span (a)
    and (b) can only honestly be labelled with the section, so a size-driven
    split throws away the precision that makes a citation worth checking.

    Adjacent subdivisions are merged only when each is smaller than `min_chars`.
    That keeps a section of twenty one-line definitions from becoming twenty
    chunks, and leaves anything substantial alone with its own label.
    """
    if indices is None:
        indices = list(range(len(blocks)))
    if not indices:
        return []

    def size(run: list[int]) -> int:
        return sum(len(blocks[i].text) + 2 for i in run)

    units = _units(blocks, indices, depth)
    deeper_exists = any(blocks[i].marker is not None and blocks[i].depth > depth for i in indices)

    # No structure left to follow at or below this level: the run is as split as
    # the document can justify, so size decides.
    if len(units) == 1 and not deeper_exists:
        run = units[0]
        if size(run) <= budget:
            return [run]
        packed: list[list[int]] = []
        current: list[int] = []
        for i in run:
            if current and size(current) + len(blocks[i].text) + 2 > budget:
                packed.append(current)
                current = []
            current.append(i)
        if current:
            packed.append(current)
        return packed

    if len(units) == 1:
        return _group(blocks, paths, depth + 1, budget, min_chars, units[0])

    out: list[list[int]] = []
    for unit in units:
        if size(unit) <= budget:
            out.append(unit)
        else:
            out.extend(_group(blocks, paths, depth + 1, budget, min_chars, unit))

    # Merge runs of small neighbours. The label is recomputed from the merged
    # blocks afterwards, so a merge can widen a label but never narrow one.
    merged: list[list[int]] = []
    for run in out:
        if (
            merged
            and size(run) < min_chars
            and size(merged[-1]) < min_chars
            and size(merged[-1]) + size(run) <= budget
        ):
            merged[-1] = merged[-1] + run
        else:
            merged.append(run)
    return merged


def _split_oversized(text: str, limit: int) -> list[str]:
    """Break one over-long block at sentence boundaries.

    Only ever called on a single block, which is already inside one subdivision,
    so no split here can cross a section or mislabel a chunk.
    """
    if len(text) <= limit:
        return [text]

    pieces: list[str] = []
    buffer = ""
    for sentence in re.split(r"(?<=[.;])\s+", text):
        candidate = f"{buffer} {sentence}".strip()
        if len(candidate) <= limit or not buffer:
            buffer = candidate
        else:
            pieces.append(buffer)
            buffer = sentence
    if buffer:
        pieces.append(buffer)
    return pieces


def chunk_section(
    section: Section,
    citation_base: str,
    target_chars: int = TARGET_CHARS,
    min_chars: int = MIN_CHARS,
) -> list[Chunk]:
    """Chunks for one section, each labelled with a unit that contains it.

    `citation_base` is the section's citation as a reader would write it, e.g.
    "42 U.S.C. § 7412". Subdivision markers are appended to it.
    """
    blocks = section.blocks
    if not blocks:
        return []

    heading = f"{citation_base}. {section.heading}".strip().rstrip(".") + "."
    # The heading rides on every chunk. A passage retrieved from the middle of a
    # long section otherwise arrives with no indication of what law it is, and
    # the model has to infer that from the text, which is the kind of inference
    # this whole design exists to make unnecessary.
    budget = target_chars - len(heading) - 2
    if budget < min_chars:
        budget = min_chars

    paths = _paths(blocks)
    groups = _group(blocks, paths, depth=0, budget=budget, min_chars=min_chars)

    chunks: list[Chunk] = []
    for group in groups:
        label = _label(citation_base, _common([paths[i] for i in group]))
        text = "\n\n".join(blocks[i].text for i in group)
        for piece in _split_oversized(text, budget):
            chunks.append(Chunk(section_label=label, ordinal=0, text=f"{heading}\n\n{piece}"))

    # Ordinals count within a label, so (section_label, ordinal) is unique and a
    # citation to § 7412(a) backed by two chunks is expressible.
    counters: dict[str, int] = {}
    numbered: list[Chunk] = []
    for chunk in chunks:
        ordinal = counters.get(chunk.section_label, 0)
        counters[chunk.section_label] = ordinal + 1
        numbered.append(Chunk(section_label=chunk.section_label, ordinal=ordinal, text=chunk.text))
    return numbered
