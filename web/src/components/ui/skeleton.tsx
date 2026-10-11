import type * as React from "react";

import { cn } from "@/lib/utils.ts";

/** A placeholder block for content that is on its way.
 *
 *  Always paired with a live region that says what is loading in words. A
 *  pulsing rectangle tells a screen reader nothing, and the animation is
 *  turned off wholesale under `prefers-reduced-motion`.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("animate-pulse rounded bg-secondary", className)}
      {...props}
    />
  );
}

export { Skeleton };
