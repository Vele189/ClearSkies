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
export default function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-slate-50 px-5 py-3 text-xs text-slate-600">
      <p className="mx-auto max-w-5xl">
        Burden scores describe patterns in public environmental records. They are not
        findings of wrongdoing by any facility or operator, and nothing here is legal
        advice. Generated documents are drafts requiring human review.
      </p>
    </footer>
  );
}
