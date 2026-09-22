import Link from "../components/Link.tsx";
import { PageTitle, Point, Prose, Section } from "../components/Prose.tsx";

/** What the drafting assistant does, will not do, and where it fails (CS-405).
 *
 *  **What is deliberately not here: an audit result presented as production
 *  behaviour.** The fifty-draft citation audit met its gate on fixture
 *  hexagons, because Phase 2 had not loaded a populated database when it ran.
 *  The statutes and facilities were real and every verification ran against
 *  them, which is what makes the citation result meaningful; the scores and
 *  demographics were invented to span the spread. CP-15 repeats it against a
 *  promoted run and CP-22 replaces this section with that result. Until then
 *  this page says what was actually measured and what it was measured on.
 */
export default function ModelCardPage() {
  return (
    <div>
      <PageTitle>The drafting assistant</PageTitle>

      <Prose>
        <p>
          The assistant turns one hexagon's public records into a first draft of an
          advocacy document. It writes four kinds: a public comment letter, an agency
          complaint draft, a community briefing sheet and a journalist fact sheet.
        </p>
        <p>
          Every output is labelled a draft requiring human review. There is no send
          button and no publish path anywhere in this system, by design.
        </p>
      </Prose>

      <Section title="What it is for">
        <p>
          A well-cited public comment takes hours of skilled work, which is a real
          barrier for the communities carrying the most burden. This produces a starting
          point in seconds, grounded in records a reader can check, so the skilled hours
          go into judgement rather than into assembling citations.
        </p>
      </Section>

      <Section title="What it is not for">
        <Point label="Not legal advice.">
          Nothing it writes is legal advice, and nothing it writes should be filed
          without review by someone qualified to file it.
        </Point>
        <Point label="Not a finished document.">
          It has not read the local context, the procedural posture, or anything a
          resident knows. It has read the databases.
        </Point>
        <Point label="Not a lawsuit.">
          A Title VI disparate-impact claim is an administrative complaint to an agency,
          not a case that can be filed in federal court. The schema permits one forum for
          that reason, so the model cannot describe it as litigation even if asked.
        </Point>
        <Point label="Not usable on a hexagon we do not trust.">
          A hexagon in the insufficient confidence band cannot be drafted from at all.
          The band is not a member of the type the drafting path accepts, so this is a
          refusal the code cannot forget to make.
        </Point>
      </Section>

      <Section title="The guardrails, and which layer each one lives in">
        <p>
          Four of them, deliberately in different places. A rule that exists only in the
          prompt can be argued with; a rule that exists only in code is one the model
          keeps trying to break. The important ones are in more than one layer, and each
          layer fails differently.
        </p>
        <Point label="Structured output.">
          Every claim carries a citation, as a required field on a schema rather than as
          an instruction. Citations are a structured type, not prose, so a plausible
          sentence cannot pass as a reference.
        </Point>
        <Point label="A sealed corpus.">
          Statutes come only from a versioned corpus — the Clean Air Act, Title VI, the
          Louisiana Environmental Quality Act and the state's public trust provision. A
          sealed version refuses writes at the database rather than by convention, so the
          model cannot cite a statute that is not in it and the corpus cannot grow at
          runtime.
        </Point>
        <Point label="Citation verification, including what a citation is for.">
          Every record id and statute section is checked against the database before a
          draft is rendered, and every distinct citation-and-claim pair is judged
          separately: a section that genuinely exists still fails if it does not support
          the proposition attached to it. A draft with one unverifiable citation is
          discarded whole, not shown with a warning.
        </Point>
        <Point label="Facts-only language rules.">
          Documented facts and statistical patterns only, and never a claim about a
          company's intent, motive or knowledge. This is the one rule that cannot be made
          structural — there is no type that expresses "does not attribute a motive" — so
          it rests on the prompt and is measured rather than enforced.
        </Point>
      </Section>

      <Section title="What has been measured, and on what">
        <p>
          An adversarial red-team set is run against the real model and its results are
          committed rather than asserted. The citation verifier is checked against real
          statute sections with deliberate traps — sections that exist but do not support
          the claim made of them — and true propositions it must not reject.
        </p>
        <p>
          A fifty-draft citation audit has been run and met its gate: 49 drafts from 50
          attempts, 184 citations, zero unverifiable citations in any draft shown. The
          one discarded draft is the system working — the verifier found a statute cited
          for a proposition it does not support and threw the document away.
        </p>
        <Point label="That audit ran on fixture hexagons, and is not yet a statement about production.">
          The statutes and the facilities in it were real, and every verification ran
          against them, which is what makes the citation result meaningful. The scores
          and demographics were invented, because no populated database existed when it
          ran. It has to be repeated against real scores before it can be read as a
          description of what this deployment does, and this page will say so when it
          has been.
        </Point>
      </Section>

      <Section title="Known limitations">
        <Point label="It is only as good as the corpus.">
          Authorities that are not in the corpus cannot be cited, including ones that
          would strengthen a particular argument. What is in it is documented.
        </Point>
        <Point label="Verification proves existence and support, not sufficiency.">
          A verified citation means the record exists and the section says what the draft
          says it says. It does not mean the argument built on it is a good one.
        </Point>
        <Point label="It has no local knowledge.">
          Everything it knows came from federal and state databases, which are
          incomplete in ways the sources page documents.
        </Point>
      </Section>

      <Section title="Versions">
        <p>
          Drafts are produced with OpenAI's gpt-4o under prompt version v3, and every
          draft records the prompt version and model that produced it. A released prompt
          version is frozen and checksummed; changing a prompt means adding a version,
          because a draft cited later has to be reproducible from what made it.
        </p>
        <p>
          How the score itself is built is on{" "}
          <Link
            to="/methodology"
            className="text-sky-800 underline focus-visible:outline-2
                       focus-visible:outline-offset-2 focus-visible:outline-sky-700"
          >
            the methodology page
          </Link>
          .
        </p>
      </Section>
    </div>
  );
}
