import assert from "node:assert/strict";
import test from "node:test";

import {
  buildUniverseRoute,
  mountUniverseApp,
  parseUniverseRoute,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  NAV,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import {
  DETAIL_RENDERERS,
  TAB_RENDERERS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

// The shell reads plus an empty runs table — enough for any Delivery facet.
function deliveryClient() {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, name: "Yoke" }] });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({ rows: [] });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountAt(t, hash, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, mounted };
}

test("a view declares its second segment — tabs or drill-in, never both", () => {
  const tabbed = NAV.filter((entry) => entry.tabs);
  assert.ok(tabbed.length > 0);
  for (const entry of tabbed) {
    assert.ok(entry.tabs.length > 0);
    // The same segment cannot be a tab and a drill-in at once.
    assert.ok(!(entry.id in DETAIL_RENDERERS), entry.id);
    // Every unbuilt tab must say what it will be.
    for (const tab of entry.tabs) {
      const live = Boolean((TAB_RENDERERS[entry.id] || {})[tab.id]);
      assert.ok(live || tab.summary, `${entry.id}/${tab.id}`);
    }
    // A live tab renderer must belong to a declared tab.
    for (const tabId of Object.keys(TAB_RENDERERS[entry.id] || {})) {
      assert.ok(entry.tabs.some((tab) => tab.id === tabId), tabId);
    }
  }
  // Tab renderers only hang off views that declared tabs.
  for (const viewId of Object.keys(TAB_RENDERERS)) {
    assert.ok(NAV.some((entry) => entry.id === viewId && entry.tabs), viewId);
  }
});

test("tab routes round-trip; absent and unknown segments resolve to the first tab", () => {
  assert.deepEqual(parseUniverseRoute("#/delivery/flows?project=3"), {
    view: "delivery", tab: "flows", detail: null, project: "3",
  });
  assert.equal(
    buildUniverseRoute("delivery", "3", "flows"),
    "#/delivery/flows?project=3",
  );
  assert.deepEqual(parseUniverseRoute("#/delivery"), {
    view: "delivery", tab: "runs", detail: null, project: null,
  });
  assert.equal(parseUniverseRoute("#/delivery/nonsense?project=2").tab, "runs");
  // A tabbed view's segment is a facet, never a drill-in detail — so an
  // unknown segment resolves instead of surviving as a detail.
  assert.equal(parseUniverseRoute("#/delivery/flows").detail, null);
});

test("a deep-linked unbuilt tab renders its stub under the active nav item, with no picker", async (t) => {
  const client = deliveryClient();
  const { documentNode, root, mounted } = await mountAt(
    t, "#/delivery/flows?project=1", client,
  );

  // Delivery stays the active destination; the tab never becomes one.
  const activeNav = byClass(root, "nav-link")
    .filter((node) => node.classList.contains("active"));
  assert.equal(activeNav.length, 1);
  assert.equal(
    allNodes(activeNav[0])
      .find((node) => node.classList.contains("txt")).textContent,
    "Delivery",
  );

  const tabLinks = byClass(root, "tab-link");
  assert.deepEqual(
    tabLinks.map((node) => node.textContent),
    ["Runs", "Environments", "Flows", "Databases", "Infrastructure"],
  );
  const activeTabs = tabLinks
    .filter((node) => node.classList.contains("active"));
  assert.equal(activeTabs.length, 1);
  assert.equal(activeTabs[0].textContent, "Flows");
  // Tabs are real links that carry the view's scope.
  assert.equal(activeTabs[0].href, "#/delivery/flows?project=1");

  // The honest stub: Coming soon, what it will be, and no scope control.
  assert.equal(byClass(root, "stub-panel").length, 1);
  const text = allNodes(root)
    .map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("Coming soon"));
  assert.ok(text.includes("The pipeline definitions runs execute."));
  assert.equal(byClass(root, "scope-bar").length, 0);
  assert.equal(byClass(root, "project-chooser").length, 0);

  // A stub reads nothing beyond the shell's own roster calls.
  assert.deepEqual(
    client.requests.map((request) => request.function).sort(),
    ["organizations.get", "projects.list"],
  );
  // The deep link survives untouched.
  assert.equal(
    documentNode.defaultView.location.hash, "#/delivery/flows?project=1",
  );
  mounted.unmount();
});

test("a tabbed route with no segment renders its first tab without rewriting the hash", async (t) => {
  const client = deliveryClient();
  const { documentNode, root, mounted } = await mountAt(
    t, "#/delivery?project=1", client,
  );

  const activeTabs = byClass(root, "tab-link")
    .filter((node) => node.classList.contains("active"));
  assert.equal(activeTabs.length, 1);
  assert.equal(activeTabs[0].textContent, "Runs");
  // Resolution is a render decision, not a URL mutation: the bare route
  // stays shareable exactly as the viewer wrote it.
  assert.equal(
    documentNode.defaultView.location.hash, "#/delivery?project=1",
  );
  mounted.unmount();
});

test("Runs fills from deployment runs, newest first, with grounded status pills", async (t) => {
  const requests = [];
  const runRow = (id, status, stage) => ({
    id, project: "yoke", flow: "yoke-hosted-production", target_env: "production",
    release_lineage: null, status, current_stage: stage,
    created_at: `${id}-created`, started_at: null, completed_at: null,
    created_by: "usher",
  });
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, name: "Yoke" }] });
      }
      if (request.function === "deployment_runs.list") {
        // Engine order: oldest first.
        return okEnvelope({
          rows: [
            runRow("run-20260101-001", "succeeded", "complete"),
            runRow("run-20260102-001", "failed", "test-failed"),
            runRow("run-20260103-001", "created", null),
            runRow("run-20260103-002", "executing", "ci-gate"),
          ],
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const { root, mounted } = await mountAt(t, "#/delivery/runs?project=1", client);

  // The read carries the view's scope in the payload and keeps the proxy's
  // server-side global target default.
  assert.deepEqual(
    requests.find((request) => request.function === "deployment_runs.list"),
    { function: "deployment_runs.list", payload: { project: "1" } },
  );

  // A built tab carries its own picker.
  assert.equal(byClass(root, "project-chooser").length, 1);
  assert.equal(byClass(root, "stub-panel").length, 0);

  // Newest run first; the stage is text the engine owns, never a bar.
  const firstCells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .slice(0, 6)
    .map((node) => node.textContent ||
      (node.children[0] && node.children[0].textContent) || "");
  assert.deepEqual(firstCells, [
    "run-20260103-002", "yoke-hosted-production", "production", "ci-gate",
    "executing", "run-20260103-002-created",
  ]);

  // Grounded status vocabulary maps to semantic pill families; values the
  // hint has not seen (created) wear neutral idle.
  const pillFamilies = Object.fromEntries(
    byClass(root, "pill").map((node) => [
      node.attributes.get("data-state"),
      node.className.replace("pill", "").trim(),
    ]),
  );
  assert.deepEqual(pillFamilies, {
    executing: "run",
    succeeded: "good",
    failed: "crit",
    created: "idle",
  });
  mounted.unmount();
});

test("every unbuilt Delivery tab renders the stub treatment and never a picker", async (t) => {
  for (const tabId of [
    "environments", "flows", "databases", "infrastructure",
  ]) {
    const client = deliveryClient();
    const { root, mounted } = await mountAt(
      t, `#/delivery/${tabId}?project=1`, client,
    );
    assert.equal(byClass(root, "stub-panel").length, 1, tabId);
    assert.equal(byClass(root, "project-chooser").length, 0, tabId);
    assert.ok(
      !client.requests.some(
        (request) => request.function === "deployment_runs.list",
      ),
      tabId,
    );
    mounted.unmount();
  }
});
