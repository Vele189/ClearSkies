import { PageTitle, Point, Prose, Section } from "../components/Prose.tsx";
import { TextLink } from "../components/Link.tsx";

/** How the score is built, and what it does and does not mean.
 *
 *  Not a copy of the paper. The paper is the authority and is linked; this is
 *  the part a reader needs in order to read the map honestly, which is mostly
 *  section 15 and the two pieces of arithmetic that surprise people. Written
 *  for someone who has never seen a percentile table: docs/frontend.md
 *  section 9 has the plain-language glossary it follows.
 */
export default function MethodologyPage() {
  return (
    <div>
      <PageTitle
        lede="What the colours on the map mean, how we work them out, and what they can't
              tell you."
      >
        How it works
      </PageTitle>

      <Prose>
        <p>
          The map divides Louisiana into small six-sided areas, each about a quarter of a
          square mile (0.7 km²). Every area gets a result made of two halves: how much
          pollution it carries, and how vulnerable the people living there are. It follows
          the same approach as CalEnviroScreen and EJScreen, two widely used government tools.
        </p>
        <p>
          Each half is built from measures such as cancer risk from toxic air, how many large
          polluters are nearby, and how many residents are young children or on low incomes.
          Fifteen measures in all. On each one, an area is compared with every other area in
          Louisiana, and the colour on the map shows where it ranks overall: the darkest red
          is the most burdened tenth of the state.
        </p>
        <p>
          We wrote down exactly how the ranking works, and the weight each measure carries,
          before writing any of the code that calculates it, so the result could not be
          quietly adjusted to give a wanted answer. Any change since is recorded.
        </p>
      </Prose>

      <Section title="Two things that surprise people">
        <Point label="The two halves are multiplied, not added.">
          A place with very heavy pollution but few vulnerable residents can end up lower
          than a place that is middling on both. For example, an area more polluted than 95%
          of the state but less vulnerable than most scores about 19; an area that is above
          average on both scores about 36. That is by design: pollution does the most harm
          where people are least able to cope with it.
        </Point>
        <Point label="Rankings only compare places within Louisiana.">
          An area in the middle of the Louisiana ranking might carry more pollution than the
          worst areas of another state. The map makes no claims about the country as a whole.
        </Point>
      </Section>

      <Section title="Race is shown, but never used to calculate the result">
        <p>
          Every area&apos;s panel shows who lives there, including race, and we study how
          race and pollution line up. But race is never one of the measures. This is
          deliberate, and it is the most important choice in the whole method.
        </p>
        <p>
          The question this project tests is whether pollution in Louisiana falls hardest on
          Black communities. If race were part of the formula, the answer would be built in:
          areas would rank high partly because more Black residents live there, and finding
          a link would prove nothing. Leaving race out means any link we find is real.
        </p>
        <p>
          That choice has a cost, and we say so openly: the ranking can understate the burden
          on a Black community that is not also poor, because it can&apos;t see the ways race
          matters on its own. We accept that cost so the finding can be trusted, not because
          we think the effect is small.
        </p>
      </Section>

      <Section title="How sure we are is shown on the map">
        <p>
          For every area we also work out how much we really know about it: how complete the
          data is, how recent it is, how precisely we know who lives there, and how far away
          the nearest air monitor is. Where we are less sure, the area is drawn with stripes.
          We use stripes rather than fading the colour, because a faded colour would look like
          less pollution.
        </p>
      </Section>

      <Section title="What the ranking is not">
        <Point label="Not a health risk for any one person.">
          It compares places. It can&apos;t tell you anyone&apos;s chance of getting ill.
        </Point>
        <Point label="Not a finding of wrongdoing.">
          A high ranking means estimated pollution, nearby industry and a vulnerable
          population. It says nothing about whether any plant broke a law or meant any harm.
          Plants that follow their permits exactly still count toward it.
        </Point>
        <Point label="Not a clean bill of health at the low end.">
          A low ranking can mean little pollution, or it can mean the data that would have
          shown pollution is missing. &ldquo;How sure we are&rdquo; tells the two apart, so
          always read it alongside the result.
        </Point>
        <Point label="Not a substitute for local knowledge.">
          People who live in a place know things no government database does. The map is a
          starting point for a conversation, not the last word.
        </Point>
      </Section>

      <Section title="What is missing">
        <p>
          It has no health records. Rates of asthma, low birth weight and heart disease would
          make the &ldquo;how vulnerable are residents&rdquo; half much better, but no free
          source publishes them for small enough areas across the country. So that half
          relies on age and income alone. This is the biggest gap in the method, and we say
          so.
        </p>
        <p>
          It covers Louisiana only. Water quality, soil contamination, drinking water,
          pesticides and traffic are not included in this version.
        </p>
      </Section>

      <Section title="Where the numbers come from">
        <p>
          Five public sources: EPA records on plants and their permits, the toxic chemical
          releases plants report each year, EPA estimates of toxic air, readings from air
          monitors, and census data.{" "}
          <TextLink to="/provenance">The data sources page</TextLink> shows when each was last
          updated and what it leaves out.
        </p>
      </Section>
    </div>
  );
}
