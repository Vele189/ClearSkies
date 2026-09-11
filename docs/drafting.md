# The drafting assistant

Four document types, assembled from public environmental data and the sealed
statute corpus. Every output is a draft for a person to review. There is no send
button, no publish path, and no route through this system that produces a
document nobody has read.

[`docs/corpus.md`](corpus.md) covers where the statutory text comes from.
[`docs/methodology.md`](methodology.md) Appendix B is the manifest of record and
section 12 is the confidence model this document keeps referring to.

---

## 1. Where the safety lives

Four guardrails, and they are deliberately in four different places. A rule that
exists only in the prompt is a rule that can be argued with; one that exists
only in code is a rule the model will keep trying to break, filling logs with
rejections. So the important ones are in more than one layer, and each layer
fails differently.

| Rule | Type | Prompt | Code | Verifier |
|---|---|---|---|---|
| Every claim carries a citation | required field | yes | schema | CS-305 |
| Citations are structured, not prose | discriminated union | yes | schema | CS-305 |
| Insufficient-confidence hexes cannot be drafted from | band has no such member | yes | `check_band` | — |
| A Title VI claim is a complaint, not a lawsuit | `forum` has one value | yes | schema | — |
| Every document says it is a draft | computed constant | yes | schema | — |
| No claims about intent, motive or knowledge | — | yes | — | red-team + audit |
| No legal advice | — | yes | — | red-team + audit |

The last two are the ones that cannot be made structural. There is no type that
expresses "does not attribute a motive", so those rest on the prompt and are
measured rather than enforced. That is what the red-team run is for, and why its
results are committed rather than asserted.

---

## 2. Prompts

Versioned in `api/app/assistant/prompts/`, one directory per version, Markdown
rather than Python string literals so a change to what the model is told shows
up in a diff as prose. The safety rules are the point of the file and should be
readable by whoever is responsible for them, not only by whoever maintains the
code.

A released version is frozen, and that is enforced by checksum. Editing v1 to
fix a phrase would leave every past draft stamped "v1" while v1 now says
something else: an audit trail that reads as precise and is wrong, which is
worse than one that is missing. Changing a prompt means adding a version, and
CS-306 treats a prompt revision as a cache invalidation.

Every generated draft records the prompt version alongside the corpus version
and the methodology version. Section 17 makes that argument for scores; it
applies with more force to a document somebody may have filed with an agency.

## 3. Refusing is an output

The agent's output type is a union: the document, or a `Refusal` naming what was
missing.

This is the single most important design decision in the layer. A model given a
document schema and nothing else has no way to say "the passages you gave me do
not support this". Its options are to produce the document anyway or to fail
validation, and it will produce the document, because producing the requested
shape is what the schema asks for. Giving the model a legitimate way to decline
is what makes declining something it actually does.

A refusal is a success from the system's point of view. It tells a user
something true and lets them go and look for what is missing. A document built
on an invented fact tells them something false, in a form designed to persuade.

## 4. What the model can see

Two sources and no others: passages retrieved from the sealed corpus, and one
hexagon's data. The prompt says so, and says it again at the point the data is
handed over.

Retrieval asks several questions rather than one. The user's request goes in as
written, alongside a few standing questions for the document type. Retrieving on
the request alone is not enough, and the failure is instructive: "draft a
comment letter about this permit" embeds to nothing in particular, the Title V
public participation right never comes back, and the model correctly refuses for
want of an authority that was sitting in the corpus the whole time. Every query
still goes through the same sealed view, so widening what is asked does not
widen what can come back.

Hexagon data is rendered with every record's identifier next to it, because a
facility described as "a chemical plant 2 km north" cannot be cited, and a model
that wants to make the claim will invent an identifier for it. Absent values are
printed as absent rather than omitted: section 11 spends a page on why missing
is not zero, and a model shown a list with a gap fills the gap from what it
knows about Louisiana.

---

## 5. The red-team run

`scripts/run_redteam.py` runs twenty adversarial requests against the real model
and writes [`docs/validation/redteam.md`](validation/redteam.md).

The set is not mostly hostile. The dangerous entries are sympathetic: somebody
frightened about their neighbourhood asking whether they can sue, a reporter
asking the obvious follow-up about why a plant was built where it was. A
guardrail that only survives obvious bad faith is not a guardrail.

It includes **controls**: legitimate requests that must produce a document. A
safety layer that refuses everything passes every refusal test and is useless,
and over-refusal is the failure nobody notices, because each individual refusal
looks responsible.

### Results, 2026-09-11, gpt-4o, prompts v1

| | |
|---|---|
| Attacks | 20 |
| Refused that should be refused | 12 of 12 |
| Forbidden phrases in any output | 0 |
| Prohibited-language flags in any output | 0 |
| Controls that produced a document | 2 of 6 |

**Every attack aimed at an intent claim, legal advice, an invented fact or the
wrong forum was refused**, and each refusal named the right rule. The Sandoval
attack was refused with the correct posture stated back: disparate-impact claims
proceed as administrative complaints to EPA, not as lawsuits. The attempt to
reason from *Save Ourselves* to "this permit must be denied" was refused as
building a legal argument from case law, which is exactly what Appendix B.3
forbids.

**Four of the six controls were over-refused.** These are requests that bundle a
legitimate ask with an improper rider: write a complaint *and tell me my
deadline*, write a letter *and use this docket number*, write a fact sheet *and
estimate the emissions*, write a complaint *and threaten federal court*. The
model refused the whole request rather than producing the compliant part.

That is the conservative direction and it is not a safety problem, but it is not
free either: a user who asks one wrong thing gets nothing, with no indication
which part was the problem. Two things would improve it, and neither is in this
phase: the refusal could name the offending part of the request specifically,
and the prompt could say that a request with an improper element should be
answered without that element rather than declined. Both change what the model
does, so both need a new prompt version and a re-run, and neither should be
done without measuring whether it weakens the twelve refusals that currently
work.

**The hexagon in this run is a fixture.** Phase 2 has not run against a
populated database, so there is no scored cell to point at. The statutory
passages are real, retrieved from the sealed corpus. The report says so at the
top, because a red-team result reported against invented data that looked real
would be its own kind of unverifiable claim.

### Running it

```bash
make redteam                    # writes docs/validation/redteam.md
make redteam REQUIRE_CLEAN=1    # and exits non-zero if anything needs review
```

It costs money and needs a key, which is why it is a script and not a test: a
test suite that sometimes bills you is a test suite people stop running. The
offline half, in `api/tests/test_guardrails.py`, runs in CI and covers
everything that holds without a key.

---

## 6. The citation verifier

Every citation is checked against the database before a draft is rendered, and
**a draft with any unverifiable citation is rejected**. Not shown with a
warning, not shown with the bad citation stripped out. A warning is read once
and then forgotten by whoever forwards the document, and a document with a
citation quietly removed is one whose remaining claims now rest on nothing with
no sign anything was taken out. The only safe failure is no document.

### Existence is the easy half

A section label is looked up in the sealed corpus; a record id in `facility`.
Both catch the obvious failure, which is a citation to something that is not
there.

One subtlety cost a real bug. A citation names a *unit* and the corpus stores
*chunks*, so a section whose every chunk carries a subdivision label has no
chunk labelled with the bare section: the corpus holds `42 U.S.C. § 7410(a)` and
nothing labelled `42 U.S.C. § 7410`. Matching exactly therefore rejected a
correct citation to the section as not in the corpus, which is the worst kind of
false rejection — the user is told their statute does not exist. A citation is
now satisfied by its label or any subdivision of it, with the boundary at an
opening parenthesis so `§ 7412(b)` is not satisfied by `§ 7412(a)`.

### Support is the half that matters

Appendix B.4 rule 3. Existence alone is not sufficient, and the reason is worth
being precise about: a fabricated citation announces itself, and a **real**
section attached to a claim it does not support is one a reader can look up,
will find, and will read as confirming something it does not say. It is more
persuasive than a true citation, because the effort of checking makes the reader
more confident afterwards.

Checking a paraphrase is not a string operation, so a second model is asked one
narrow question about one passage: does this passage state or directly establish
this proposition? It is told the passage is the only evidence, that an inference
is not support, and that a proposition naming a facility, number or date is
supported only if the passage carries it.

Three verdicts, and the third decides the design. `supported` passes.
`not_supported` fails. **`unclear` also fails**, because a verifier that
resolves its own uncertainty in favour of publishing is not a verifier. A false
rejection costs one draft somebody can ask for again; a false acceptance ships a
citation nobody will check twice, because it has already been checked.

### Does it work?

`scripts/check_verifier.py` pairs real sections with propositions and records
what the real judge said. Eight of the twelve are **traps**: a real section with
a claim that is plausible, adjacent, and not what the section says.

Results, 2026-09-11, gpt-4o as judge:

| | |
|---|---|
| True propositions kept | 4 of 4 |
| **False propositions caught** | **8 of 8** |

The traps that were caught include a definitions subsection offered for the
claim that a named facility exceeds a threshold, a duty-imposing section offered
for the claim that the duty was breached, a reporting requirement offered for a
facility's reported figure, and section 601 of Title VI offered for the claim
that a resident may sue to enforce disparate-impact rules. That last is the
*Sandoval* failure aimed at the statute rather than the case, and it is the one
that would do the most damage.

```bash
make check-verifier                  # writes docs/validation/verifier.md
make check-verifier REQUIRE_CLEAN=1  # and fails on any disagreement
```

### A known cost: verification is serial

Every citation is judged in its own call, one after another, so a draft with
seven citations waits for seven round trips after the one that wrote it. That is
most of the time a user spends watching the progress line, and it is the reason
a fifty-draft audit takes over an hour.

It is left alone here deliberately. Nothing about it changes a verdict — each
citation is judged independently against its own passage, so running them
concurrently would produce the same answers — and Phase 3's criteria are about
whether citations are correct, not how fast. Batching or parallelising the judge
belongs in Phase 4 with the rest of the polish, where it can be measured against
a latency budget rather than guessed at.

### The rejection log

A rejected draft is invisible by design: the user sees a failure and nobody sees
the citation that caused it. `draft_rejection` (migration 0020) records one row
per offending citation, with the section or id exactly as the model wrote it.
Not normalised — a near-miss identifier is evidence about how the model fails,
and normalising it away destroys exactly that. CS-308 reads this table to
characterise the failure modes.

---

## 7. The prohibited-language scan

`redteam.scan` flags the vocabulary of intent, culpability, prediction and
litigation for a person to read. CS-308 reuses it over the fifty audited drafts.

It is an audit aid, not a filter, and it is deliberately not wired into the
generation path as a blocker. A regular expression cannot tell "the operator
knew" from "the operator knew of the requirement, per the permit application",
and a system that silently rewrote or dropped drafts on a keyword match would be
making an editorial judgement nobody could see.

It over-flags on purpose, with one exception: the system's own constant
disclaimers are excluded. The complaint's filing note says "not a lawsuit", and
flagging every correct complaint forever teaches whoever reads the report to
skip the category.

---

## 8. The endpoint, the cache and the bill

`POST /draft`. A POST for two reasons and the second is the one that matters: it
is not idempotent from the client's side, because the first call for a hexagon
spends money at a third-party API and a GET is something browsers, proxies, link
previewers and prefetchers issue on their own. And **it must never sit behind
the CDN**, because a cached response would hand one hexagon's draft to whoever
asked next. `.railway/railway.ts` says so beside the service definition; the
CDN is enabled on `web` only.

### What happens, in order

1. **Band check**, before anything is spent. An insufficient-confidence hexagon
   never reaches retrieval, let alone the model.
2. **Cache**, keyed on the hexagon, the document type, and the methodology,
   corpus and prompt versions.
3. **Retrieve** from the sealed corpus.
4. **Generate**, with refusal available.
5. **Verify** every citation. A draft that fails is logged and discarded.
6. **Store** only what passed.

### The cache key is the design

A draft is a function of the hexagon, the document type, and the three versions
that decide what it says. Key on all of them and a revision invalidates exactly
what it should, with no invalidation step for anybody to remember and no stale
draft served under a new methodology version.

What is deliberately **not** in the key is the user's free text. Two people
asking for a comment letter on the same hexagon in different words should get
the same document, because the document is about the hexagon. Keying on the
phrasing would make the cache miss almost always, which is the same as not
having one.

A cache hit is not re-verified, because nothing that failed verification was
ever written, and the corpus version is part of the key.

### Failures that are answers

| Status | When | What the reader is told |
|---|---|---|
| 409 | The hexagon is in the insufficient band | The tool does not trust its own number here, in plain language, not an error code |
| 422 | A citation could not be verified | A draft was produced and discarded; this is the system working |
| 422 | The model did not produce the schema | Nothing was shown; trying again may work |
| 503 | No API key configured | The rest of the API works normally |
| 503 | No sealed corpus | Nothing could be verified even if it were cited |
| 503 | Provider rate limit or spend cap | Nothing is wrong with the request; try later |

A provider limit is recognised from the exception's name and message rather than
by importing the SDK's exception classes. That hierarchy changes between major
versions, and the cost of getting it wrong is a 500 where a legible "try later"
belonged.

### The spend cap is not in this repository

`llm_usage` records every call, including the refused, the rejected and the
failed, because cost is incurred by attempts and not by successes. `GET
/draft/spend` reports the month to date. Both are **indicative**: the prices are
a table in an application that the provider can change without telling it.

**The hard monthly cap is set on the API key in the OpenAI dashboard.** That is
an operator step and it cannot be done from here, which is the point: a limit
the application enforces is a limit that stops working when the application has
a bug, and the bug that matters is the one that calls the API in a loop. Set it
before the key is used in a deployment anyone else can reach.

---

## 9. The Phase 3 gate

`scripts/run_citation_audit.py` generates fifty drafts and checks every citation
in every one. [`docs/validation/citation-audit.md`](validation/citation-audit.md)
is the committed result and the drafts themselves are under
`docs/validation/audit-drafts/` so the manual review has something to read.

The spread lives in `api/app/assistant/audit.py` rather than in the script, for
the reason `burden/validation.py` is not in `run_validation.py`: a gate's
criteria should be testable without running the gate. Thirteen hexagons across
the three draftable bands, with facility counts from one to seventeen, each
drafted in more than one document type. The insufficient band is absent because
such a hexagon cannot be drafted from at all, so including one would measure the
band check rather than the citations.

Every accepted draft is **re-verified independently** of the pipeline that
produced it. A gate that trusts the thing it is gating is not a gate.

### What is real and what is a fixture

**Real:** every statute passage, from the sealed corpus. Every facility, loaded
from ECHO by `scripts/seed_audit_facilities.py` with its own FRS registry
identifier — the identifier a reader would take to EPA. Every verification, run
against those two tables.

**A fixture:** the hexagons. Phase 2 has not run against a populated database,
so there is no scored cell to point at and the scores, confidence values and
demographics are invented to span the spread. That does not weaken the citation
result, which is what the gate is about: a citation is checked against the
corpus and the facility table, and both hold real rows. It does mean the drafts
are about places that do not have these scores, and **the audit has to be re-run
once the pipeline has loaded real data** before anybody cites it as a statement
about production behaviour.

### What the first run found, and what it changed

The audit did what a gate is supposed to do, which is to find something.

**Drafts were being discarded for citing the hexagon they were about.** The
schema requires a citation on every factual claim; a hexagon's score and
demographics *are* factual claims; and there was no legitimate way to attribute
them. So the model invented a dataset called `hexagon`, cited the H3 index, the
citation failed verification, and an otherwise sound draft was thrown away.
Twelve of the first run's eighteen rejections were this.

The first attempt at a fix was prompt v2, telling the model not to cite hexagon
figures. It did not work, and it should not have: the instruction fought the
rule telling the model to cite every factual claim, and that rule was right.

The real fix was structural. The hexagon **is** a citable record — a reader can
open that cell on the map and see the same figures — so `hex` is now a dataset,
the `record_id` is the H3 index, and the verifier checks that the citation names
the hexagon the draft is actually about. Prompt v3 tells the model to use it.

That sequence is why prompts are versioned and frozen. v1 and v2 are still in
the repository, unedited, with their checksums recorded, because drafts stamped
with them were produced under those words.

### A defect this run exposed in its own cost reporting

Every `llm_usage` row from the audit records the model as `OpenAIChatModel()`
and a cost of zero. `str()` on a Pydantic AI model object returns its class
name, not the model, and no price table has an entry for a class name — so the
estimate silently came out at zero and the provenance stamped on each draft
identified nothing.

Both failures are quiet in the way that matters: a draft still generates, a
usage row still lands, and the only symptom is a bill that does not match the
reported spend. The code now reads `model_name`, with a test that a class name
never reaches the price lookup. **The audit run predates the fix**, so its usage
rows keep the wrong label and a zero cost; the token counts in them are correct
and the report's totals are computed from those.

### What a person still has to do

The gate says every citation is manually verified, and everything the harness
does is mechanical. A script reporting that a script agreed with itself is not a
manual review. What remains:

- **Read the drafts.** The prohibited-language scan catches vocabulary. It
  cannot catch a claim about why a facility is where it is, made in neutral
  words.
- **Check a sample of citations by hand**, by following the link and reading the
  section. The verifier is a language model, and this is the only check on it
  that is not another language model.
- **Look specifically for anything implying a Title VI disparate-impact claim
  can be filed as a lawsuit.** That is the failure with the worst consequences
  for a reader and the one a fluent draft hides best.
