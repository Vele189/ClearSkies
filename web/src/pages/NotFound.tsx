import { ArrowLeft } from "lucide-react";

import Link from "../components/Link.tsx";
import { Mono } from "../components/Prose.tsx";
import { Button } from "../components/ui/button.tsx";

/** A path nothing answers.
 *
 *  It names the path, because the commonest way to arrive here is a truncated
 *  or mistyped link and a reader can usually see the problem once they are
 *  shown what was asked for.
 */
export default function NotFound({ path }: { path: string }) {
  return (
    <div className="py-6">
      <p className="text-xs font-semibold tracking-[0.06em] text-faint uppercase">
        No such page
      </p>
      <h1 className="mt-2 text-3xl font-semibold sm:text-4xl">Nothing at this address</h1>
      <p className="measure mt-4 font-serif text-[1.0625rem] leading-[1.7] text-body">
        There is no page at <Mono className="text-muted-foreground">{path}</Mono>.
      </p>
      <Button asChild variant="outline" className="mt-7">
        {/* asChild over `Link`, not over a bare `<a>`: it has to render an
            anchor so a reader can middle-click it and a screen reader
            announces a link, and it has to be the router's anchor or the
            click leaves the application and reloads it. */}
        <Link to="/">
          <ArrowLeft aria-hidden="true" />
          Back to the map
        </Link>
      </Button>
    </div>
  );
}
