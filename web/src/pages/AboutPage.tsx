import { TextLink } from "../components/Link.tsx";
import { PageTitle, Point, Prose, Section } from "../components/Prose.tsx";

export default function AboutPage() {
  return (
    <div>
      <PageTitle
        lede="A map of how much pollution each part of Louisiana lives with, built only from
              public records, and honest about where the data is thin."
      >
        About ClearSkies
      </PageTitle>

      <Prose>
        <p>
          ClearSkies brings together government records on industrial plants, the toxic
          chemicals they report releasing, EPA estimates of air pollution, air monitor
          readings and census data about who lives where. From these it ranks every small
          area of Louisiana by how much pollution it carries and how vulnerable the people
          living there are. Click any area on the map to see why it ranks where it does,
          which plants are nearby, and how sure we are.
        </p>
        <p>
          The evidence that polluting industry is unevenly spread is already public. It is
          just scattered across several government databases, each with its own format and
          quirks. Putting it together is most of the work.
        </p>
      </Prose>

      <Section title="Please read these before using it">
        <Point label="This is not legal advice.">
          Nothing on this site is legal advice. Nothing it helps you write should be filed,
          sent or published until someone qualified has reviewed it.
        </Point>
        <Point label="A high ranking is not an accusation.">
          It describes a pattern in public data. It is not a finding of wrongdoing by any
          plant or company, and plants that follow their permits to the letter still count
          toward the ranking.
        </Point>
        <Point label="Drafts are drafts.">
          Every document the site writes is marked as needing human review. There is no send
          button: you copy or download it and decide what happens next.
        </Point>
        <Point label="A low ranking is not a clean bill of health.">
          It can mean there is little pollution, or that the data that would have shown it
          is missing. Always check &ldquo;How sure we are&rdquo; next to the result.
        </Point>
      </Section>

      <Section title="What it covers">
        <p>
          Louisiana only, and only air pollution and industrial plants. Rankings compare
          places within Louisiana. Water quality, soil contamination, drinking water,
          pesticides, traffic and health records are not included in this version.
        </p>
        <p>
          It also doesn&apos;t cover other states, doesn&apos;t have user accounts, and never
          delivers anything on your behalf.
        </p>
      </Section>

      <Section title="Data and licence">
        <p>
          All of the data comes from US government sources and is in the public domain. The
          code is free and open source (MIT licence). The{" "}
          <TextLink to="/provenance">data sources page</TextLink> lists each source, when it
          was last updated and what it leaves out;{" "}
          <TextLink to="/methodology">how it works</TextLink> explains how the ranking is
          built; and <TextLink to="/model-card">document drafts</TextLink> explains the
          writing assistant.
        </p>
      </Section>
    </div>
  );
}
