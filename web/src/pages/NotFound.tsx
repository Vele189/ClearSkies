import Link from "../components/Link.tsx";

/** A path nothing answers.
 *
 *  It names the path, because the commonest way to arrive here is a truncated
 *  or mistyped link and a reader can usually see the problem once they are
 *  shown what was asked for.
 */
export default function NotFound({ path }: { path: string }) {
  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">Nothing at this address</h1>
      <p className="mt-3 text-sm text-slate-700">
        There is no page at <span className="font-mono text-xs">{path}</span>.
      </p>
      <p className="mt-6 text-sm">
        <Link
          to="/"
          className="text-sky-800 underline focus-visible:outline-2 focus-visible:outline-offset-2
                     focus-visible:outline-sky-700"
        >
          Back to the map
        </Link>
      </p>
    </div>
  );
}
