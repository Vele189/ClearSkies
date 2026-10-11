import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Join class names, last conflicting Tailwind utility winning.
 *
 *  shadcn's components all expect this helper at this path. `clsx` handles the
 *  conditionals and `twMerge` resolves the conflicts, so a caller passing
 *  `className="px-6"` to something whose variant already sets `px-3` gets six
 *  rather than two classes fighting in the cascade.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
