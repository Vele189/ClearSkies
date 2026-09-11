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
