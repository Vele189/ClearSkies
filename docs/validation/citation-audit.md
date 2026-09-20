# CS-308 — fifty-draft citation audit

- Date: 2026-09-11
- Model: `gpt-4o`
- Prompt version: `v3`
- Corpus: `appendix-b-4ff29b03c9be`

## The gate

| | |
|---|---|
| Drafts attempted | 50 |
| Drafts produced | 49 |
| Drafts refused by the model | 0 |
| Drafts discarded by the verifier | 1 |
| Errors | 0 |
| Citations in produced drafts | 184 |
| **Unverifiable citations in a shown draft** | **0** |

**Zero unverifiable citations reached a shown draft.** Every citation in every produced draft was re-checked independently of the pipeline that produced it, and all of them resolved: each statute section exists in the sealed corpus and supports the proposition it was cited for, and each record id exists in the facility table.

The 1 drafts the verifier discarded are the system working. They were never rendered; they are counted here because the rate at which the assistant produces unsupportable citations is worth knowing even when none of them reaches a reader.

## Spread

| Band | Drafts | Produced | Refused | Discarded |
|---|---|---|---|---|
| high | 12 | 11 | 0 | 1 |
| moderate | 19 | 19 | 0 | 0 |
| low | 19 | 19 | 0 | 0 |

| Document type | Drafts | Produced | Citations |
|---|---|---|---|
| public_comment_letter | 13 | 12 | 45 |
| agency_complaint_draft | 13 | 13 | 61 |
| community_briefing_sheet | 12 | 12 | 37 |
| journalist_fact_sheet | 12 | 12 | 41 |

Hexagons with two or fewer contributing facilities: 19 drafts, 19 produced. This is where a model is most tempted to pad a thin document with something it remembers.

## Language review

The prohibited-language scan ran over the model's own words in all 49 produced drafts, excluding this system's constant disclaimers. Drafts with at least one flag: **15**.

Each needs a person to read the sentence:

### industrial-moderate — community_briefing_sheet

- **culpability** `wrongdoing` — ...the presence of vulnerable communities. However, this score is not a direct accusation of wrongdoing by any company or facility. It's a model used to understand potential environmental risks...

### industrial-moderate-2 — journalist_fact_sheet

- **culpability** `wrongdoing` — ...ilities are mentioned based on proximity and potential impact classification but imply no wrongdoing. record 884446003dfffff hex The burden score is 74.9, placing the hexagon in the 88.0 per...

### rural-low-2 — community_briefing_sheet

- **culpability** `wrongdoing` — ...indicates potential environmental concerns. However, it does not imply that any specific wrongdoing has occurred or that any specific health issues are present within the community. Attend...

### rural-low-sparse — journalist_fact_sheet

- **culpability** `wrongdoing` — ...tted sources, and the demographics of the population. It does not constitute a finding of wrongdoing by any operator. record 884446007dfffff hex The burden score for this hexagon is 44.6 out...
- **culpability** `wrongdoing` — ...measurement. The presence of the AIR LIQUIDE facility is noted without any implication of wrongdoing or regulatory non-compliance. record 884446007dfffff hex The burden score for this hexago...

### urban-moderate-many — community_briefing_sheet

- **culpability** `wrongdoing` — ...to toxics, presence of nearby sources, and community vulnerability. It does not indicate wrongdoing or serve as a health diagnosis. Attend public hearings regarding environmental issues in...

### northern-low — journalist_fact_sheet

- **culpability** `wrongdoing` — ...note that the score and other metrics are based on modelled data and are not findings of wrongdoing. Two facilities contributing to the emissions score in this hexagon are ARCOSA LW BR LLC...

### river-high-few — community_briefing_sheet

- **culpability** `wrongdoing` — ...ure to air toxins, particulate matter, and other pollutants. This is not an indication of wrongdoing by any facilities nearby. Attend public hearings about air quality standards in your area...

### urban-moderate-many — journalist_fact_sheet

- **culpability** `wrongdoing` — ...ed burden score. The burden score is not an indicator of legal compliance or a finding of wrongdoing by any facility or operator. record 884446017dfffff hex The burden score for the hexagon...

### dense-corridor-high — community_briefing_sheet

- **culpability** `wrongdoing` — ...ities nearby. This may affect air quality and health, yet it is not a direct indicator of wrongdoing or health outcomes. The score is based on state-level comparisons. Attend local governmen...

### rural-low — journalist_fact_sheet

- **culpability** `wrongdoing` — ...d exposure, nearby permitted sources, and a vulnerable population. It is not a finding of wrongdoing by any operator. record 88444601fdfffff hex The hexagon has a burden score of 62.7, placi...

### rural-low-sparse — agency_complaint_draft

- **culpability** `wrongdoing` — ...zards, nearby permitted sources, and a vulnerable population, and is not an indication of wrongdoing by any operator. record 884446021dfffff hex The cumulative burden score for this hexagon...

### coastal-low — community_briefing_sheet

- **culpability** `wrongdoing` — ...llution and its sources, including air toxins and particulate matter. This does not imply wrongdoing by any company. It shows potential risks and persistent social factors that can affect ho...

### border-moderate — community_briefing_sheet

- **culpability** `wrongdoing` — ...ial activity nearby. It highlights potential exposure to pollutants but does not conclude wrongdoing or link directly to health issues. Stay informed about local industrial activities by acc...

### suburban-moderate — journalist_fact_sheet

- **culpability** `wrongdoing` — ...and other indicators describe modelled exposure and nearby sources, but do not imply any wrongdoing by specific operators. The modelled air toxics cancer risk in this area is 55.7 per milli...

### rural-low-sparse — community_briefing_sheet

- **culpability** `wrongdoing` — ...your area in Concordia Parish. It is based on available public data and not a finding of wrongdoing by any operators. The area has a burden score of 44.6 out of 100, which places it in the...
- **culpability** `wrongdoing` — ...nd factors like air toxics cancer risk, it is not a health diagnosis nor an indication of wrongdoing by local facilities or operators. Attend public hearings on environmental issues. Comment...

## Refusals

None.

## Discarded by the verifier

- `dense-corridor-high` / public_comment_letter: 42 U.S.C. § 7661a(b) (unsupported) The passage states that no permit will be issued if the Administrator objects, but it does not specifically mention 'due to potential environmental risks' as a reason for objection.

## Cost

51 model calls, 140,334 tokens, about $0.44 estimated. Generation and verification both; the verifier runs a second model over every citation, and attributing all of it to generation would mislead about where the money goes.

## What is a fixture, and what is real

**Real:** every statute passage, retrieved from the sealed corpus. Every facility, loaded from ECHO with its own FRS registry identifier — the same identifier a reader would take to EPA. Every verification, run against those two tables.

**A fixture:** the hexagons. Phase 2 has not run against a populated database, so there is no scored cell to point at, and the scores, confidence values and demographics here are invented to span the spread the gate asks for. This does not weaken the citation result, which is what the gate is about: a citation is checked against the corpus and the facility table, and both hold real rows. It does mean the drafts are about places that do not have these scores, and **this audit must be re-run once the pipeline has loaded real data** before the model card cites it as a statement about production behaviour.

## What a person still has to do

The gate says every citation is manually verified. A script reporting that a script agreed with itself is not that, and the checks above are all mechanical:

- **Read the drafts.** They are written to the directory this run names. The scan catches vocabulary; it cannot catch a claim about why a facility is where it is, made in neutral words.
- **Check a sample of citations by hand**, by following the link and reading the section. The verifier is a language model and this is the only check on it that is not another language model.
- **Look specifically for anything implying a Title VI disparate-impact claim can be filed as a lawsuit.** That is the failure with the worst consequences for a reader, and it is the one a fluent draft hides best.
