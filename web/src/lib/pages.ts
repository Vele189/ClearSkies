/** Where the site's pages live, in the order the navigation lists them.
 *
 *  One list, extended by the ticket that adds each page, so a nav entry and the
 *  route behind it arrive together and the nav never points at a 404. It lives
 *  apart from `Nav` because a module that exports both a component and a
 *  constant loses fast refresh.
 */
export const PAGES: { path: string; label: string }[] = [
  { path: "/", label: "Map" },
  { path: "/provenance", label: "Sources" },
];
