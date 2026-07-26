import assert from "node:assert/strict";
import test from "node:test";

import {
  buildUniverseRoute,
  mountUniverseApp,
  parseUniverseRoute,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  createScopePicker,
  navEntry,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  cellText,
  injectedClient,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

// A two-project universe whose items are distinguishable per project, for
import {
  itemsCalls, scopeChips, twoProjectClient,
} from "./universe_ui_read_views_test_support.mjs";

test("Sessions shows the session: actor, liveness, lane, mode, and what it holds", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, name: "Yoke" }] } } };
      }
      if (request.function === "sessions.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [
                {
                  session_id: "s-run", liveness: "active",
                  execution_lane: "primary", mode: "charge",
                  actor_id: 2, actor_kind: "human", actor_label: "Ben",
                  claims: [
                    { target_kind: "item", target: "YOK-41" },
                    { target_kind: "process", target: "feed" },
                  ],
                  current_item: "YOK-41", activity_at: "now",
                },
                {
                  session_id: "s-idle", liveness: "stale",
                  execution_lane: "primary", mode: "wait",
                  actor_id: 1, actor_kind: "system",
                  actor_label: "yoke-core",
                  claims: [], current_item: null, activity_at: "then",
                },
              ],
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.deepEqual(
    requests.find((request) => request.function === "sessions.list"),
    { function: "sessions.list", payload: { project: "1" } },
  );
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "s-run", "Ben", "active", "primary", "charge", "YOK-41, feed",
    "YOK-41", "now",
    "s-idle", "yoke-core · system", "stale", "primary", "wait", "",
    "", "then",
  ]);
  // Liveness colors through the semantic pill families: alive reads good,
  // stale reads warn — derived states, never re-encoded thresholds.
  const pills = allNodes(root)
    .filter((node) => node.classList && node.classList.contains("pill"));
  assert.deepEqual(
    pills.map((pill) => pill.className),
    ["pill good", "pill warn"],
  );
  // The read served its complete set, so the panel counts the merged rows.
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 2");
  mounted.unmount();
});
test("every routed view opens with its page head, and only summarized entries get a subtitle", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, name: "Yoke" }] } } };
      }
      if (request.function === "sessions.list") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      if (request.function === "items.list.run") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  // The head names the view and carries its NAV summary as the subtitle.
  const heads = byClass(root, "page-head");
  assert.equal(heads.length, 1);
  const title = byClass(heads[0], "title")[0];
  assert.equal(title.tagName, "H1");
  assert.equal(title.textContent, "Sessions");
  assert.equal(
    byClass(heads[0], "subtitle")[0].textContent,
    "Each session: who runs it, what it holds, and how alive it is.",
  );
  // The head leads the content column, above the view's own picker.
  const content = byClass(root, "content")[0];
  assert.ok(content.children[0].classList.contains("page-head"));
  assert.ok(content.children[1].classList.contains("scope-bar"));

  // An entry with no summary renders no empty subtitle node at all.
  documentNode.defaultView.location.hash = "#/items?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  const itemsHead = byClass(root, "page-head")[0];
  assert.equal(byClass(itemsHead, "title")[0].textContent, "Items");
  assert.equal(byClass(itemsHead, "subtitle").length, 0);
  mounted.unmount();
});

test("Inbox renders its decided empty-state model under one page head", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/inbox";
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, name: "Yoke" }] } } };
      }
      if (request.function === "inbox.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              needs_decision: [],
              requests: [],
              notifications: [],
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  const head = byClass(root, "page-head")[0];
  assert.equal(byClass(head, "title")[0].textContent, "Inbox");
  assert.equal(
    byClass(head, "subtitle")[0].textContent,
    "Decisions waiting on you, and what happened while you were away.",
  );
  assert.equal(byClass(root, "stub-panel").length, 0);
  assert.equal(byClass(root, "inbox-empty").length, 3);
  assert.equal(byClass(root, "raw-toggle").length, 0);
  mounted.unmount();
});

test("the items count is the served total, summed across buckets — never rows.length", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/items?project=1,2";
  const root = documentNode.createElement("div");
  const itemRow = (id, project) => ({
    id, title: "t", workflow_id: "issue", workflow_version_id: 1, status: "idea", priority: "medium",
    blocked: "0", blocked_reason: "", project,
  });
  // Each bucket serves one row of a larger total, so the served counts and
  // the merged rows.length deliberately disagree.
  const servedByBucket = {
    1: { rows: [itemRow(11, "alpha")], count: 3 },
    2: { rows: [itemRow(21, "beta")], count: 4 },
  };
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [
                { id: 1, slug: "alpha", name: "Alpha" },
                { id: 2, slug: "beta", name: "Beta" },
              ],
            },
          },
        };
      }
      if (request.function === "items.list.run") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: servedByBucket[request.payload.project],
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  // Two rows render, but the engine attested seven: the served number wins.
  assert.equal(
    allNodes(root).filter((node) => node.tagName === "TD").length > 0, true,
  );
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 7");
  mounted.unmount();
});
