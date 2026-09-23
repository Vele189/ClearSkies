# Documentation index

Everything under `docs/`, and what each file is for. The methodology paper is
the authority on what the numbers mean; every other page here either implements
it, records a result it demanded, or explains how to operate a part of it.

## The specification

| Document | What it is |
|---|---|
| [methodology.md](methodology.md) | The paper. Indicators, weights, normalization, eligibility, confidence, the validation protocol, the revision changelog, and Appendix B's statute manifest. Written before the code and changed only by a documented revision. |
| [backlog.md](backlog.md) | Every ticket, by phase, with its owner, dependencies and status judged against what is in the repository. |

## Operating the system

| Document | What it is |
|---|---|
| [database.md](database.md) | The Neon branch, the container alternative, how a schema change lands, and what each table is for. |
| [nightly.md](nightly.md) | The scheduled ETL run: which sources are due, the budget, and what a failed night does. |
| [quality.md](quality.md) | The data quality gate a night has to clear before its run can be promoted. |
| [provenance.md](provenance.md) | Per source: the release, the retrieval time, the checksum and the known gaps. Its generated block is rewritten by the nightly job. |
| [corpus.md](corpus.md) | The statute corpus: what is in it, how a version is built, embedded and sealed, and the operator commands. |
| [drafting.md](drafting.md) | The drafting assistant: where each safety rule lives, what the red team found, and how the citation verifier is checked. |
| [frontend.md](frontend.md) | How the map draws a score and how it draws how much we trust it: the ramp, the legend, the confidence bands, the detail panel. |

## Validation results

Committed as they came out, passing or failing. Methodology section 13.7
permits three responses to a failing check and none of them is editing these.

| Document | What it is |
|---|---|
| [validation/sites.yml](validation/sites.yml) | The pre-registered validation set: thirty sites, committed before any scoring code existed. Read-only and append-only. |
| [validation/anchor-references.yml](validation/anchor-references.yml) | Independent coordinates each anchor in `sites.yml` was checked against. |
| [validation/anchor-verification.md](validation/anchor-verification.md) | CS-111: the result of that check. |
| [validation/site-validation.md](validation/site-validation.md) | CS-206, sections 13.2 to 13.4: the phase gate. Run 11 is a FAIL at 7 of 10 primary sites and 2 of 4 negative controls. |
| [validation/robustness.md](validation/robustness.md) | CS-212, section 13.5: whether the score is an artifact of its own construction. Run 11 is a FAIL on four indicators; section 7 holds the result. |
| [validation/disparity.md](validation/disparity.md) | CS-213, section 13.6: burden percentile against racial composition. A reported result with no threshold, and the independence argument that makes it one. |
| [validation/citation-audit.md](validation/citation-audit.md) | CS-308: the fifty-draft audit, with the drafts themselves in `validation/audit-drafts/`. |
| [validation/citation-audit-review.md](validation/citation-audit-review.md) | What a person found reading those fifty drafts, kept apart from what the harness measured. |
| [validation/redteam.md](validation/redteam.md) | The adversarial set run against the real model. |
| [validation/safe-language.md](validation/safe-language.md) | CS-407: the pass over everything user-facing, and the scan that repeats it on every CI run. |
| [validation/verifier.md](validation/verifier.md) | The citation judge against real sections: eight traps and four true propositions. |

## The 2026-09-22 audit

| Document | What it is |
|---|---|
| [audit/2026-09-22-codebase-audit.md](audit/2026-09-22-codebase-audit.md) | A read-only review of the whole repository, by area, with each finding coded. |
| [audit/tickets.md](audit/tickets.md) | The fifteen tickets that resolve those findings, with acceptance criteria. |

## Finishing it

| Document | What it is |
|---|---|
| [plan/tickets.md](plan/tickets.md) | The twenty-five tickets between the repository as it stands and the Phase 2 exit condition, then Phase 4. Sequenced, with the decision points named. |

The repository's own [README](../README.md) covers what the project is,
[CONTRIBUTING.md](../CONTRIBUTING.md) covers how to work on it, and
[etl/README.md](../etl/README.md) covers adding a data source.
