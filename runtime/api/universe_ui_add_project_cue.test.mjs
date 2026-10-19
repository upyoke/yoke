// A viewer who can see no project is routed to their own harness agent,
// with the harness names the registry publishes, wherever a page is empty
// for want of a project.

import assert from "node:assert/strict";
import test from "node:test";

import { ADD_PROJECT_CUE } from "../../packages/yoke-core/src/yoke_core/ui/static/add_project_cue.js";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { renderNewItemView } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_new.js";
import { renderProjectsView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_projects.js";
import { FakeDocument, allNodes, response, settle } from "./universe_ui_dom_test_support.mjs";

const textOf = (root) => allNodes(root).map((node) => node.textContent || "").join(" ");

function fixedClient(results) {
  return {
    async call(request) {
      const result = results[request.function];
      if (!result) throw new Error(`unexpected function ${request.function}`);
      return { status: 200, envelope: { success: true, result } };
    },
  };
}

test("the cue names every registered harness", () => {
  assert.equal(
    ADD_PROJECT_CUE, "Ask Claude Code, Codex, or Cursor to add a project to Yoke.",
  );
});

test("a single-project page over an empty universe routes to the agent", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/architecture";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: fixedClient({
    "organizations.get": { name: "Yoke" },
    "projects.list": { rows: [] },
  }) });
  await settle();
  assert.ok(textOf(root).includes(ADD_PROJECT_CUE));
  assert.ok(textOf(root).includes("No projects yet"));
  mounted.unmount();
});

for (const rows of [[], [{ id: 1, slug: "acme", name: "Acme" }]]) {
  test(`the Projects page teaches adding a project with ${rows.length} rows`, async () => {
    const document = new FakeDocument(), main = document.createElement("div");
    renderProjectsView({
      document, isMounted: () => true, client: fixedClient({ "projects.list": { rows } }),
    }, main);
    await settle();
    assert.ok(textOf(main).includes(ADD_PROJECT_CUE));
  });
}

for (const [roster, expected] of [
  [[], ADD_PROJECT_CUE],
  [[{ id: 7, slug: "acme" }], "Ask a project owner for access."],
]) {
  test(`New item with no creatable project and ${roster.length} visible`, async () => {
    const document = new FakeDocument(), main = document.createElement("div");
    renderNewItemView({
      document, projects: () => roster, isMounted: () => true, navigate: () => {},
      client: fixedClient({ "projects.list": { creation_scoped: true, rows: [] } }),
    }, main, "all");
    await settle();
    assert.ok(textOf(main).includes(expected));
  });
}
