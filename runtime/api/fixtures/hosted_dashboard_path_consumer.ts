import routes from "../../.generated/universe-contract/dashboard-routes.json";

/** The pinned Yoke wheel owns the route roster and hosted mount base. */
export function hostedDashboardBasePath(slug: string): string {
  return routes.hostedBasePathTemplate.replace("{slug}", encodeURIComponent(slug));
}

/** Serve only dashboard destinations; API and asset paths stay separate. */
export function isHostedDashboardPath(parts: readonly string[]): boolean {
  if (parts.length === 0) return true;
  if (!routes.views.includes(parts[0])) return false;
  const tabs = routes.tabs as Record<string, string[]>;
  const hasTab = tabs[parts[0]]?.includes(parts[1]);
  return parts.length <= (hasTab ? 3 : 2);
}

export type HostedPageQuery = Readonly<Record<string, string | string[] | undefined>>;

export function hostedDashboardUrl(
  slug: string,
  parts: readonly string[] = [],
  query: HostedPageQuery = {},
): string {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    for (const entry of Array.isArray(value) ? value : [value]) {
      if (entry !== undefined) search.append(name, entry);
    }
  }
  const path = parts.length ? `/${parts.map(encodeURIComponent).join("/")}` : "";
  return `${hostedDashboardBasePath(slug)}${path}${search.size ? `?${search}` : ""}`;
}
