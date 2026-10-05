import { NAV, parseUniverseRoute, buildUniverseRoute, routePath } from "./universe_navigation.js";
import { DETAIL_RENDERERS } from "./universe_views.js";
import { callFunction } from "./universe_view_support.js";

const bareLocation = (href, base) => href === (base || "/") || href === `${base}/`;

// Only a bare entry spends this read. Resource checks use the same authority
// as the page itself; a stored route is never evidence of current access.
export async function locationResolves(client, href, projects, sections = {}, basePath = "") {
  if (typeof href !== "string" || !href.startsWith("/")) return false;
  const path = routePath(href, basePath).slice(1).split("?")[0].split("/");
  const entry = NAV.find((candidate) => candidate.id === path[0]);
  if (!entry || (entry.hostFed && !sections[entry.id])) return false;
  let route;
  try { route = parseUniverseRoute(href, basePath); } catch { return false; }
  if (path.length > (route.tab ? 3 : 2) || path.some((part) => !part)) return false;
  const accessible = (id) => projects.some((row) => String(row.id) === id);
  for (const scope of [route.project, route.selection]) {
    if (scope !== null && scope !== "all" && !scope.split(",").every(accessible)) return false;
  }
  if (!route.detail) return true;
  const project = route.project || String(projects[0]?.id || "");
  const detail = route.detail;
  const read = async (functionId, payload = {}, target) => {
    const response = await callFunction(client, functionId, payload, target);
    return response.status === 200 && response.envelope?.success
      ? response.envelope.result : null;
  };
  try {
    if (route.view === "workflows") {
      const result = await read("workflows.definition.get");
      return Boolean(result?.workflows?.some((row) => row.id === detail));
    }
    if (!DETAIL_RENDERERS[route.view]) return false;
    switch (route.view) {
      case "items":
        if (detail.toLowerCase() === "new") return Boolean(project);
        return Boolean((await read("items.detail.get", {}, {
          kind: "item", public_ref: detail, project_id: project,
        }))?.item);
      case "strategy":
        return Boolean((await read("strategy.surface.get", { slug: detail }, {
          kind: "global", project_id: project,
        }))?.document);
      case "projects": return accessible(detail);
      case "machines":
        return Boolean((await read("machine.detail", { machine_id: detail }))?.machine);
      case "sessions": {
        const result = await read("sessions.list", { session_id: detail, project });
        return Boolean(result?.rows?.some((row) => String(row.session_id) === detail));
      }
      case "shipping":
      case "deployments": {
        if (route.tab === "flows") {
          const result = await read("workflows.definition.get");
          return Boolean(result?.flows?.some((row) => String(row.id) === detail));
        }
        const result = await read("deployment_runs.list", { page: { search: detail } });
        return Boolean(result?.rows?.some((row) => String(row.id) === detail));
      }
      case "qa-methods":
        return Boolean((await read("qa.method.get", { method_id: detail, project }))?.method);
      case "qa-plans":
        return Boolean((await read("qa.plan.get", { plan_id: Number(detail), project }))?.plan);
      case "qa-activity":
        return Boolean((await read("qa.requirement.get", {}, {
          kind: "qa_requirement", qa_requirement_id: Number(detail),
        }))?.requirement);
      case "ouroboros":
        return Boolean((await read("ouroboros.entry.get", {
          entry_id: Number(detail), project,
        }))?.entry);
      case "capabilities":
        return detail === "test-machine" && Boolean(await read("test_machine.list", { project }));
      default: return false;
    }
  } catch { return false; }
}

export function createLocationPreference({ client, windowNode, navigation, selections, isMounted, onFallback }) {
  const entryHref = navigation.current();
  let lastSaved = null;
  let writes = Promise.resolve();
  let restored = null;
  return {
    client: {
      async call(request, init) {
        const href = restored;
        const result = await client.call(request, init);
        const code = result.envelope?.error?.code || "";
        // A global page can lose permission too. Its own renderer supplies
        // the access verdict, without adding a duplicate permission read.
        const denied = [401, 403, 404].includes(result.status) ||
          /not_found|not_allowed|forbidden|denied|unauthorized|permission|authz/.test(code);
        if (href && denied && isMounted() && routePath(navigation.current(), navigation.basePath) === href) {
          restored = null;
          navigation.replace(buildUniverseRoute(NAV[0].id));
          onFallback?.();
        }
        return result;
      },
    },
    async restore(projects, sections) {
      if (!bareLocation(entryHref, navigation.basePath) || navigation.current() !== entryHref) return;
      const saved = selections.lastLocation;
      if (!saved) return;
      const valid = await locationResolves(client, saved, projects, sections);
      // A navigation or unmount during the resource read wins too.
      if (!isMounted() || navigation.current() !== entryHref) return;
      const href = valid ? saved : buildUniverseRoute(NAV[0].id);
      restored = valid ? href : null;
      navigation.replace(href);
    },
    remember() {
      const location = navigation.current();
      if (restored && routePath(location, navigation.basePath) !== restored) restored = null;
      if (!selections.ready || !location || location === lastSaved) return;
      lastSaved = location;
      const { view } = parseUniverseRoute(location, navigation.basePath);
      // Serialize navigation writes: an earlier request cannot arrive last
      // and turn Back/Forward or a rapid click sequence into stale state.
      writes = writes.then(async () => {
        const result = await callFunction(client, "ui_preferences.screen_selection.set", {
          view_id: view, location: routePath(location, navigation.basePath),
        });
        if (!result.envelope?.success) {
          console.warn("Last page save failed", {
            code: result.envelope?.error?.code || "location_save_failed",
            status: result.status,
          });
        }
      })
        .catch((error) => {
          console.warn("Last page save failed", {
            code: "location_save_network_failed", message: String(error),
          });
        });
    },
  };
}
