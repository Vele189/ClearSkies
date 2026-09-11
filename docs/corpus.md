# The statute corpus

The drafting assistant retrieves statutory text from one place: a closed,
curated, versioned corpus built from the manifest in
[`docs/methodology.md`](methodology.md) Appendix B. There is no open web search
and no reliance on what the model remembers. A citation to anything outside this
corpus fails verification and the draft is rejected.

This document is the operator's guide. Appendix B remains the manifest of
record; nothing here overrides it.

---

## 1. What is in it

Sixteen authorities: ten federal, four Louisiana, two cases. Appendix B lists
them with their citations and why each is in scope, and
`assistant/corpus/manifest.py` restates that list as a fetch plan.

The two lists are compared by a test, in both directions, on every CI run. That
is Appendix B.4 rule 4 made structural rather than advisory: an authority added
to the code and not to the paper fails, and so does one added to the paper that
nothing ingests. The corpus cannot quietly acquire an authority, and the
methodology cannot quietly promise one.

```bash
make corpus-check      # the manifest against the paper
make corpus-manifest   # what Appendix B asks for, with the URLs
```

### Bounded case law

*Save Ourselves* and *Alexander v. Sandoval* are in the corpus with
`may_reason_from` set to false. The assistant may cite them for context and may
not reason from them to a legal conclusion. That is a column on the row rather
than a sentence in a prompt, because a prompt can be talked out of a distinction
and a boolean cannot.

*Sandoval* is there for one specific reason. A Title VI disparate-impact claim
is an administrative complaint to EPA's External Civil Rights Compliance Office,
not a lawsuit a resident can file. A draft implying otherwise sends someone down
a dead end, which is a worse failure than a missing citation, so the holding is
in the corpus where retrieval can reach it.

---

## 2. Where the text comes from

Every authority is fetched from its own publisher. Nothing is transcribed by
hand and nothing comes from an aggregator.

| Source | Publisher | How |
|---|---|---|
| United States Code | GPO, via govinfo | One HTML document per chapter or subchapter, 2024 edition |
| Code of Federal Regulations | eCFR versioner API | One XML document per part, as of a pinned date |
| Case law | Caselaw Access Project | One JSON record per opinion, by reporter, volume and file |
| Louisiana statutes and constitution | legis.la.gov | Not yet ingested; see section 4 |
| Louisiana Administrative Code | Division of Administration | Not yet ingested; see section 4 |

A whole chapter in one request rather than one request per section is a
deliberate choice, and not only politeness to the GPO. A hand-maintained list of
section numbers goes stale silently when Congress adds a section, and the corpus
would then be missing an authority while reporting itself complete.

Every document is stored with its full text, the edition or amendment date, the
URL it came from and the moment it was read, which is Appendix B.4 rule 1.

---

## 3. How it is chunked

Rule 2: chunking is by section and never crosses a section boundary, so a
retrieved passage always carries a complete citable unit.

Inside a section the split follows the statute's own structure, and the label is
**the deepest subdivision that contains the whole chunk**. A chunk holding only
§ 7412(c)(1) is cited as § 7412(c)(1); one holding (c)(1) through (c)(7) is
cited as § 7412(c); one spanning (c) and (d) is cited as § 7412.

That rule is the whole design, and the alternative is worse than it looks.
Labelling a chunk with the first marker in it produces citations that name a
subdivision the quoted text is only partly inside — a citation that exists, that
a reader can look up, and that does not say what the draft says it says. An
existence check cannot catch that, so the chunker is built so it cannot happen.

Two bugs found while building this are worth recording, because both produced
exactly that failure and both looked fine in passing:

- The US Code prints suffixed section numbers with an **en dash**, not a hyphen.
  Matching only the hyphen does not fail, it truncates: all nine sections of
  Title VI parsed as `2000d` and nine distinct authorities shared one citation.
- The letters **c, d, l and m are also Roman numerals**. Deciding a marker's
  depth by its style therefore reads clause (i) as continuing subsection (c),
  and files a clause four levels down as a subsection. A chunk of
  § 7412(c)(9)(B)(i) came out labelled § 7412(i), which is a real subsection
  about a different subject. Depth is now decided by sequence — (i) follows (h),
  and (i) does not follow (c) — not by style.

Where the publisher marks a subdivision explicitly, its letter can appear in a
citation. Where the depth had to be inferred from body text, the marker still
delimits the text but does not lend its letter to a label, and the chunk is
cited against the nearest subdivision that was marked. A broader citation is
always safe; a precise one naming a subdivision the statute does not have is
not.

---

## 4. What is not in it yet

**The four Louisiana authorities of Appendix B.2 have not been ingested.** The
Louisiana Constitution article IX section 1, the Environmental Quality Act, the
Air Control Law, and LAC 33:III are all in the manifest, all have fetch plans,
and none has been retrieved.

The reason is environmental, not a design decision. From the host this corpus
was built on, `legis.la.gov` does not resolve at all and `www.doa.la.gov`
answers 403. Both are the authoritative publishers and there is no bulk or
versioned API for either. The build reports each failure by name:

```
la-const-art9-sec1: https://legis.la.gov/...: ConnectError: Temporary failure in name resolution
lac-33-iii:         https://www.doa.la.gov/...: HTTP 403
```

What this means in practice:

- **The corpus refuses to seal.** `python -m corpus ingest --seal` exits
  non-zero and names the missing authorities. An unsealed version is invisible
  to `statute_corpus_active`, and therefore to retrieval and to the verifier, so
  an incomplete corpus is not published rather than published with a caveat.
- The version currently sealed for downstream development was sealed with
  `--force`, and the reason is recorded in its `notes` column. It covers twelve
  of sixteen authorities.
- **Drafts built on it cite federal law only.** For a Louisiana pilot that is a
  real limitation and not a cosmetic one: the public trust duty in
  *Save Ourselves* rests on a state constitutional provision whose text is not
  in the corpus. This is recorded in the model card and in the Phase 3 backlog
  entries rather than left for a reader to discover.

Finishing this needs a machine that can reach those two hosts. The fetch plans
are written and the parsers for them are not, because writing a parser against
a document nobody here has been able to open would be writing fiction.

---

## 5. Versioning and immutability

Rules 4 and 5. A corpus version is a row in `statute_corpus_version`, and every
document and chunk belongs to one. A version is open while it is being built and
**sealed** once. Sealing is a one-way door enforced by trigger in migration
`0018_statute_corpus_version`, not by convention:

| Attempt against a sealed version | Result |
|---|---|
| Insert a chunk or document | Refused |
| Update the text of a chunk | Refused |
| Delete a chunk or document | Refused |
| Move a row to another version | Refused at both ends |
| Modify or delete the version row | Refused |

The claim this project makes is that the assistant cannot cite anything outside
the corpus. That claim is worth as much as the weakest thing standing between a
process with a connection string and an INSERT, and a comment in an ingestion
script is not that. The triggers fail the same way for the ingestion script, for
`psql`, and for the API service — which is the point, since the API has no
business writing here at all and now provably cannot.

Version names are derived from the manifest hash, so two builds of the same
manifest collide rather than accumulate and a changed manifest gets a new name
without anybody choosing one. The content hash is computed over every chunk at
seal time, so "is this the corpus that draft cited" is a string comparison.

Retrieval reads `statute_corpus_active`, a view over the newest sealed version.
Forgetting to filter by version is a syntax error rather than a draft generated
against an unsealed corpus.

---

## 6. Running it

```bash
make corpus-check      # manifest against the paper; no network
make corpus-build      # fetch, parse and chunk; writes nothing
make corpus-ingest     # build, then write a corpus version
make corpus-seal       # build, write and seal, if it covers the manifest
make corpus-versions   # what the database holds
```

`corpus-build` is what CI runs. It proves the parsers still understand what the
publishers serve, which is the part most likely to break without anybody
touching this repository, and it needs no database.

Fetched documents are cached on disk under `assistant/.cache`. The cache is not
a performance feature — the whole job is a dozen requests. It is there so a
rebuild produces the same corpus as the first build: without it, "rebuild the
corpus" means "download whatever those URLs serve today", and two builds of the
same manifest version could differ. Pass `--refresh` to go back to the network,
which is for checking whether an upstream document has changed rather than for
normal use.

---

## 7. What the corpus holds today

Built 2026-09-11 against the 2024 edition of the US Code and the eCFR as of
2025-01-01.

| | |
|---|---|
| Authorities ingested | 12 of 16 |
| Documents | 12 |
| Chunks | 2,850 |
| Distinct citable labels | 2,198 |
| Embeddings | CS-302 |
