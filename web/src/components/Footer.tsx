/** The standing disclaimer, on every page rather than on the drafts alone.
 *
 *  CS-407 requires it on the app as well as on each generated document, and
 *  "on the app" has to mean every view: a reader who lands on a deep link to
 *  one hexagon has not passed through anywhere else that could have told them.
 *
 *  The wording is the methodology's, not a paraphrase. A high score describes a
 *  pattern in public data; it is not a finding about any operator, and section
 *  15 is emphatic that the difference is the project's to hold.
 */
export default function Footer({ compact = false }: { compact?: boolean }) {
  // Compact under the map, where every line it takes is a line of map lost; on
  // a phone the full-size footer took an eighth of the screen. Same words.
  return (
    <footer
      className={
        compact
          ? "border-t border-border bg-sunken px-4 py-1.5 sm:px-5"
          : "border-t border-border bg-sunken px-5 py-4"
      }
    >
      <p
        className={
          compact
            ? "mx-auto max-w-5xl text-[0.6875rem] leading-snug text-muted-foreground"
            : "mx-auto max-w-5xl text-xs leading-relaxed text-muted-foreground"
        }
      >
        Burden scores describe patterns in public environmental records. They are not
        findings of wrongdoing by any facility or operator, and nothing here is legal
        advice. Generated documents are drafts requiring human review.
      </p>
    </footer>
  );
}
