// Shared fixture for the universe search suites: a client that answers every
// domain search reads, a two-project universe so scope can be observed, and a
// mounted shell to drive. Split out because the behaviours it serves — what
// search covers, and how the dialog behaves — are two suites.

import {
  FakeDocument, response, settle,
} from "./universe_ui_dom_test_support.mjs";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  SEARCH_DEBOUNCE_MS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_shell_controls.js";

export async function settleSearch() {
  await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 20));
  await settle();
}

export function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

export function refused() {
  return {
    status: 403,
    envelope: { success: false, error: { message: "function_not_allowed" } },
  };
}

// Two projects, because the point of the scope rule is that neither the
// selector nor the project a result belongs to narrows the search.
export const PROJECTS = [
  { id: 1, slug: "yoke", name: "Yoke", public_item_prefix: "YOK" },
  { id: 3, slug: "platform", name: "Platform", public_item_prefix: "PLAT" },
];

export function fixtureClient({ overrides = {}, calls = [] } = {}) {
  const answers = {
    "organizations.get": () => ok({ name: "Yoke" }),
    "projects.list": () => ok({ rows: PROJECTS }),
    "items.overview.list": () => ok({ rows: [] }),
    "items.search.run": () => ok({ matches: [{
      id: "YOK-2228", internal_id: 2262, title: "Rebaseline the workbench",
      project_id: 1, project: "yoke", status: "implementing",
    }] }),
    "sessions.list": (payload) => (payload?.session_id ? ok({ rows: [] }) : ok({
      rows: [{
        session_id: "session-rebaseline", project_id: 1, project: "yoke",
        current_item: "YOK-2228", executor: "codex",
      }],
    })),
    "strategy.doc.list": (payload, target) => ok({
      docs: String(target?.project_id) === "3"
        ? [{ slug: "REBASELINE-PLAN", title: "Rebaseline plan", state: "active" }]
        : [],
    }),
    "qa.plan.list": (payload) => ok({
      rows: String(payload?.project) === "1"
        ? [{ id: 298, slug: "rebaseline-review", name: "Rebaseline review" }]
        : [],
    }),
    "events.query.run": (payload) => ok({
      rows: payload?.event_name ? [] : [{
        event_name: "RebaselineRecorded", project_id: 1,
        created_at: "2026-09-17T04:00:00Z", source_type: "engine",
      }],
    }),
    "packs.list": (payload) => ok({
      packs: String(payload?.project) === "1"
        ? [{ slug: "rebaseline-pack", name: "Rebaseline Pack" }]
        : [],
    }),
    "ui_preferences.search_history.list": () => ok({ queries: [] }),
    "ui_preferences.search_history.record": () => ok({ queries: [] }),
  };
  return {
    async call(request) {
      calls.push(request);
      const answer = overrides[request.function] || answers[request.function];
      if (!answer) throw new Error(`unexpected function ${request.function}`);
      return answer(request.payload, request.target);
    },
  };
}

export async function mountShell(t, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.body = documentNode.createElement("body");
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  t.after(() => mounted.unmount());
  return { documentNode, root };
}
