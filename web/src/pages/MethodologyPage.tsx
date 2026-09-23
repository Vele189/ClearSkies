import { PageTitle, Point, Prose, Section } from "../components/Prose.tsx";
import Link from "../components/Link.tsx";

/** How the score is built, and what it does and does not mean.
 *
 *  Not a copy of the paper. The paper is the authority and is linked; this is
 *  the part a reader needs in order to read the map honestly, which is mostly
 *  section 15 and the two pieces of arithmetic that surprise people.
 */
export default function MethodologyPage() {
  return (
    <div>
      <PageTitle>How the score works</PageTitle>

      <Prose>
        <p>
          Every hexagon on the map is about 0.7 km² and carries one burden score. The
          score combines how much pollution burden an area carries with how vulnerable
          the people living there are, using the structure CalEnviroScreen and EJScreen
          established. Fifteen indicators feed it, each expressed as a percentile rank
          against the rest of Louisiana.
        </p>
        <p>
          The full methodology is written down and versioned, and it was written before
          any scoring code existed so the score could not be quietly tuned to produce a
          wanted answer. Weights change only through a documented revision.
        </p>
      </Prose>

      <Section title="Two things about the arithmetic that surprise people">
        <Point label="The two halves multiply, they do not add.">
          A hexagon in the 95th percentile for pollution and the 20th for vulnerability
          scores about 19. One in the 60th percentile for both scores about 36. The
          second is higher, and that is the model working as intended: cumulative burden
          is about pollution landing on people who are least able to absorb it, not
          about pollution alone.
        </Point>
        <Point label="Percentiles are Louisiana percentiles.">
          A hexagon in the Louisiana 50th percentile may carry more burden than a
          top-decile hexagon in another state. The map makes no national claims.
        </Point>
      </Section>

      <Section title="Race is recorded, displayed, and never scored">
        <p>
          Racial composition is shown on every hexagon panel and analysed as a headline
          output, and it is not an input to the score. This is deliberate, and it is the
          most consequential decision in the methodology.
        </p>
        <p>
          The claim the project exists to test is that environmental burden in Louisiana
          falls disproportionately on Black communities. If racial composition were an
          input, that claim would be circular — the score would be high where the
          population is Black partly because the formula put it there — and the
          correlation would be guaranteed by construction and worth nothing as evidence.
          Excluding it makes the correlation an independent empirical result.
        </p>
        <p>
          It has a real cost, and the paper records it: the score understates burden in a
          Black community that is not also poor, because it cannot see the mechanisms
          that operate through race independently of income. That loss is accepted for
          the evidentiary reason, not because the effect is thought small.
        </p>
      </Section>

      <Section title="Confidence is drawn, not just reported">
        <p>
          Every hexagon carries a confidence value reflecting how much was actually known
          about it: data coverage, how old the data is, how coarse the source geography
          was, and how far the nearest air monitor is. Low-confidence hexagons are
          hatched rather than faded, because a faded fill reads as a lower score and
          would confuse how certain we are with how bad it is.
        </p>
      </Section>

      <Section title="What the score is not">
        <Point label="Not a health risk estimate.">
          It ranks burden indicators. It does not predict any individual's risk of
          illness.
        </Point>
        <Point label="Not a finding of wrongdoing.">
          A high score means high modeled exposure, nearby permitted sources, and a
          vulnerable population. It says nothing about whether any facility broke any law
          or intended any harm. Facilities operating fully within their permits
          contribute to burden scores.
        </Point>
        <Point label="Not a clean bill of health at the low end.">
          A low score can mean low burden, or it can mean the indicators that would have
          caught the burden are missing. The confidence value distinguishes the two and
          has to be read alongside the score.
        </Point>
        <Point label="Not a substitute for local knowledge.">
          Residents know things the federal databases do not contain. The score is a
          starting point for an argument, not the argument.
        </Point>
      </Section>

      <Section title="What is missing from it">
        <p>
          There are no health outcome indicators. Asthma prevalence, low birth weight and
          cardiovascular disease would materially improve the vulnerability side, and no
          free national source publishes them at tract resolution, so that side rests on
          age structure and economic hardship alone. This is the single largest gap in
          the specification and the paper records it as such.
        </p>
        <p>
          Coverage is Louisiana only. Water quality, soil contamination, drinking water,
          pesticides and traffic are all out of scope for this version.
        </p>
      </Section>

      <Section title="Where the numbers come from">
        <p>
          Five public sources: EPA compliance records, the Toxics Release Inventory,
          modeled air toxics exposure, measured air quality, and census demographics.{" "}
          <Link
            to="/provenance"
            className="text-sky-800 underline focus-visible:outline-2
                       focus-visible:outline-offset-2 focus-visible:outline-sky-700"
          >
            The sources page
          </Link>{" "}
          shows when each was last pulled and what it does not cover.
        </p>
      </Section>
    </div>
  );
}
