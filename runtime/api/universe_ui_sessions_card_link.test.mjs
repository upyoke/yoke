import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { parseUniverseRoute } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import { sessionCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import { FakeDocument, byClass, response, settle } from "./universe_ui_dom_test_support.mjs";

for (const projectId of [7, null]) {
  test(`session label links to its rendered detail with project ${projectId}`, async (t) => {
    const document = new FakeDocument();
    document.defaultView.fetch = async () => response(200, { enabled: false });
    const row = {
      session_id: "s-1", project_id: projectId, executor: "codex",
      scope_kind: projectId === null ? "org" : "project",
      project: projectId === null ? null : "example", claims: [],
    };
    const card = sessionCard(document, row, () => {});
    const link = byClass(card, "row-link").find((node) =>
      node.classList.contains("session-executor"));
    assert.equal(link.tagName, "A");
    assert.equal(link.href, `/sessions/s-1${projectId === null ? "" : "?project=7"}`);
    const route = parseUniverseRoute(link.href);
    assert.deepEqual(route, {
      view: "sessions", detail: "s-1", project: projectId === null ? null : "7",
      tab: null, selection: null,
    });
    assert.equal(byClass(link, "session-message-button").length, 0);

    const originalFetch = globalThis.fetch;
    globalThis.fetch = () => response(200, {});
    t.after(() => { globalThis.fetch = originalFetch; });
    document.defaultView.location.href = link.href;
    const root = document.createElement("div");
    const requests = [];
    const mounted = mountUniverseApp(root, {
      currentActor: { id: 1, kind: "human", label: "Reader" },
      client: { async call(request) {
        requests.push(request);
        const rows = request.function === "projects.list"
          ? [{ id: 7, slug: "example", name: "Example" }]
          : request.function === "sessions.list" ? [row] : [];
        return { status: 200, envelope: { success: true, result: { rows } } };
      } },
    });
    t.after(() => mounted.unmount());
    await settle();
    assert.equal(byClass(root, "session-detail-view").length, 1);
    assert.equal(byClass(root, "session-card")[0]?.getAttribute("data-session-id"), "s-1");
    const detailReads = requests.filter((request) =>
      request.function === "sessions.list" && request.payload.session_id === "s-1");
    assert.equal(detailReads.length, 1);
    if (projectId === null) assert.ok(!Object.hasOwn(detailReads[0].payload, "project"));
    else assert.equal(detailReads[0].payload.project, "7");
  });
}
