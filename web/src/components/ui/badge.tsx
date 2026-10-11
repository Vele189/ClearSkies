import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils.ts";

/** A short status word.
 *
 *  The `ok` / `warn` / `bad` variants are the provenance page's four pull
 *  states. Each pairs a 50-level surface with a 900-level foreground, which is
 *  the combination the contrast suite measures; the ring is decorative and is
 *  excluded from the 3:1 bar, for the reason recorded in `contrast.test.ts`.
 *
 *  Colour is never the only carrier: every badge states its status in words,
 *  so a reader who cannot separate amber from rose still reads "Failed".
 */
const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center gap-1 rounded px-2 py-0.5 text-xs font-medium " +
    "whitespace-nowrap ring-1 ring-inset [&_svg]:size-3",
  {
    variants: {
      variant: {
        default: "bg-secondary text-secondary-foreground ring-border-strong",
        outline: "bg-card text-muted-foreground ring-border-strong",
        ok: "bg-ok-surface text-ok-foreground ring-ok-border",
        warn: "bg-warn-surface text-warn-foreground ring-warn-border",
        bad: "bg-bad-surface text-bad-foreground ring-bad-border",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "span";
  return (
    <Comp data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

// Only the component is exported. shadcn ships `badgeVariants` as a public
// export, but nothing here consumes it, and a module exporting both a
// component and a value loses fast refresh -- the same reason
// `lib/pages.ts` sits apart from `Nav`.
export { Badge };
