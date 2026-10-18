import { TextLink } from "../components/Link.tsx";
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
 *
 *  Written for a reader, not a reviewer: the technical terms (structured
 *  output, sealed corpus, red-team set) are explained by what they do rather
 *  than named. docs/drafting.md has the engineering account.
 */
export default function ModelCardPage() {
  return (
    <div>
      <PageTitle
        lede="An AI assistant that turns one area's public records into a first draft you can
              check, edit and use."
      >
        Document drafts
      </PageTitle>

      <Prose>
        <p>
          From any area on the map, the assistant can write four kinds of first draft: a
          public comment letter, a complaint to a government agency, a briefing sheet for
          neighbours, and a fact sheet for journalists.
        </p>
        <p>
          Every draft is marked as needing human review. There is no send button, by design:
          you copy or download it and decide what to do with it.
        </p>
      </Prose>

      <Section title="What it is for">
        <p>
          A well-researched public comment can take hours of expert work, and that is a real
          barrier for the communities living with the most pollution. The assistant gives you
          a starting point in seconds, built on records anyone can check, so the expert time
          goes into judgement instead of hunting down references.
        </p>
      </Section>

      <Section title="What it is not for">
        <Point label="It is not legal advice.">
          Nothing it writes is legal advice. Nothing it writes should be filed until someone
          qualified to file it has reviewed it.
        </Point>
        <Point label="It is not a finished document.">
          It knows nothing about the local situation, the stage a case is at, or anything
          residents know. It has only read the government databases.
        </Point>
        <Point label="It is not a lawsuit.">
          A civil rights complaint about unequal pollution (under Title VI) goes to a
          government agency; it is not a case you can take to federal court. The assistant is
          built so it can never describe it as a lawsuit, even if asked to.
        </Point>
        <Point label="It won't write from an area we don't trust.">
          If we have too little data about an area, the assistant refuses to draft from it.
          That refusal is built into the code, so it can&apos;t be skipped by mistake.
        </Point>
      </Section>

      <Section title="The safeguards">
        <p>
          There are four, and they work in different ways by design. An instruction given
          only to the AI can be argued with, and a rule only in the code is one the AI keeps
          bumping into, so the important safeguards exist in more than one place.
        </p>
        <Point label="Every claim needs a source.">
          The assistant has to attach a source to every factual statement. That is required
          by the format it must answer in, not just requested, so it can&apos;t slip a
          reference-shaped sentence past us.
        </Point>
        <Point label="It can only cite a fixed set of laws.">
          It can only quote from a fixed, locked collection of laws: the Clean Air Act, Title
          VI of the Civil Rights Act, the Louisiana Environmental Quality Act and the
          state&apos;s public trust provision. The collection can&apos;t be added to while the
          site is running, so it can&apos;t cite a law that isn&apos;t in it.
        </Point>
        <Point label="Every source is checked before you see the draft.">
          Each record and each section of law it cites is checked against the database, and
          each one is also checked to make sure it actually says what the draft claims. A
          real law cited for something it doesn&apos;t say still fails. If even one source
          fails, the whole draft is thrown away rather than shown with a warning.
        </Point>
        <Point label="It sticks to facts.">
          It may only state documented facts and patterns in the data, never claims about a
          company&apos;s motives or state of mind. This is the one rule that can&apos;t be
          built into the format, so it rests on the instructions and is tested regularly
          rather than guaranteed.
        </Point>
      </Section>

      <Section title="What we have tested, and on what">
        <p>
          We run a set of deliberately tricky requests against the real AI and keep the
          results, rather than just claiming it behaves. We also test the source checker with
          traps: real sections of law that don&apos;t support the claim attached to them, and
          true claims it must not reject.
        </p>
        <p>
          In a test of 50 drafts, 49 were produced, with 184 sources between them and not a
          single unverifiable source in any draft shown. The one draft that was thrown away
          is the system working: the checker caught a law cited for something it doesn&apos;t
          say and discarded the document.
        </p>
        <Point label="That test used made-up areas, so it isn't yet a promise about the live site.">
          The laws and the industrial plants in it were real, and every check ran against
          them, which is what makes the result meaningful. The rankings and population
          figures were invented, because the real data hadn&apos;t been loaded yet. We need
          to repeat the test with real areas before it describes what this site does, and
          this page will say so when we have.
        </Point>
      </Section>

      <Section title="Known limits">
        <Point label="It only knows the laws it has been given.">
          Laws outside its collection can&apos;t be cited, including ones that might
          strengthen a particular argument.
        </Point>
        <Point label="A checked source isn't the same as a strong argument.">
          A checked source means the record exists and the law says what the draft claims. It
          doesn&apos;t mean the argument built on it is a good one.
        </Point>
        <Point label="It has no local knowledge.">
          Everything it knows comes from federal and state databases, which have gaps; the
          data sources page lists them.
        </Point>
      </Section>

      <Section title="Versions">
        <p>
          Drafts are written by OpenAI&apos;s gpt-4o using version 3 of our instructions, and
          every draft records which version and which AI model wrote it. Once released, a
          version of the instructions is never edited, only replaced by a new one, so any
          draft can be traced back to exactly what produced it.
        </p>
        <p>
          How the map&apos;s ranking is built is on{" "}
          <TextLink to="/methodology">how it works</TextLink>.
        </p>
      </Section>
    </div>
  );
}
