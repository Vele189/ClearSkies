import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils.ts";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md " +
    "font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 " +
    "[&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-slate-700",
        secondary: "bg-secondary text-secondary-foreground hover:bg-slate-200",
        outline: "border border-input bg-card text-foreground hover:bg-sunken",
        ghost: "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
        link: "text-link underline underline-offset-4 hover:no-underline",
      },
      size: {
        sm: "h-8 gap-1.5 px-2.5 text-xs",
        default: "h-9 px-3.5 text-sm",
        lg: "h-10 px-5 text-sm",
        // 36px square. Below ~24px a target fails WCAG 2.5.8, and an icon-only
        // control is the one most likely to be sized to its glyph.
        icon: "size-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

// Only the component is exported. shadcn ships `buttonVariants` as a public
// export, but nothing here consumes it, and a module exporting both a
// component and a value loses fast refresh -- the same reason
// `lib/pages.ts` sits apart from `Nav`.
export { Button };
