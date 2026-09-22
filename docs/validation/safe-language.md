# Safe-language and disclaimer review — CS-407

**2026-09-23, against the frontend at CP-20. Outcome: pass, with the scan
committed so the pass does not have to be remembered.**

CS-407 asks for a pass over everything user-facing, checking that the framing
holds up. The pass is below. What makes it worth more than a note is
`api/tests/test_site_copy.py`, which runs the drafting assistant's own
prohibited-vocabulary scan over the site's hand-written copy: the review is
repeated on every CI run rather than recorded once and trusted afterwards.

## Why the site copy needed this at all

The red-team scan reads generated drafts. Nothing read the copy the project
writes by hand — which is the copy a reader sees first, and the only copy no
model is ever asked to justify. A page asserting what a draft may not assert
would be the same failure with a longer half-life: a draft is reviewed before
it is used, and a page ships once.

## The disclaimer

| Criterion | Where |
|---|---|
| On the app | `components/Footer.tsx`, on every route, including a cold deep link to one hexagon |
| On every generated draft | `components/DraftPanel.tsx`, and the schema's required `draft_notice` field |
| Not legal advice | Footer, About, model card |
| Requires human review | Footer, About, model card |

The footer is on the shell rather than on the pages, so a route added later
cannot be added without it.

## What the scan found

Seven matches across six files, all read, all kept. Every one is one of two
things, and the list in the test records which:

- **The caveat itself.** "It is not a finding of wrongdoing" contains
  *wrongdoing*; the model card's "Not a lawsuit" contains *lawsuit*, *sue* and
  *federal court*. This is the over-flagging the scan was designed for — a
  phrase surfaced for review costs a moment, one missed costs a claim nobody
  checked. The test asserts each of these still sits inside a negation **in its
  own clause**, so a rewrite that dropped the "not" would fail rather than pass
  quietly.
- **The project describing its own decisions.** "Race is recorded and never
  scored. This is deliberate." The prohibition is on claims about an operator's
  state of mind. The project is entitled to describe its own, and the test
  distinguishes the two rather than exempting the word.

Both guards were checked against deliberately broken copy before being
committed — an unreviewed intent claim, and a caveat with its negation removed.
A guard that has never failed has not been shown to work.

## The explainers, against the methodology

| Claim on the site | Methodology |
|---|---|
| The two components multiply, so 60th/60th outscores 95th/20th | §10, which requires this be stated on the panel |
| Percentiles are Louisiana percentiles | §15 |
| A low score can mean low burden or missing indicators | §15, and §12 for the confidence value that distinguishes them |
| Not a finding of wrongdoing; permitted facilities contribute | §15 |
| Race recorded, displayed, never scored — and what that costs | §14, including the cost, which §14 states and a summary could easily drop |
| No health-outcome indicators; the largest gap | §3 and §16 |
| A Title VI claim is a complaint, not a lawsuit | `drafting.md` §1, where the schema permits one forum |

The race explainer carries §14's cost — that the score understates burden in a
Black community that is not also poor — and not only §14's reasoning. A page
that gave the reasoning alone would read as a defence of the decision rather
than a description of it.

## No send, submit or publish path

Asserted in `test_there_is_no_send_submit_or_publish_path` rather than left to
inspection. It fails on a `mailto:`, a `<form>`, a POST to anywhere other than
the drafting endpoint, or `navigator.share`. The one POST the frontend makes is
`/draft`, which asks the API to write a document and hand it back.

## What this does not cover

The scan reads vocabulary. It cannot read a sentence that implies a motive
without using any of the words, and `run_citation_audit.py` says the same thing
about drafts. That is what a human pass is for, and this document is one; the
test is what keeps it from silently expiring.
