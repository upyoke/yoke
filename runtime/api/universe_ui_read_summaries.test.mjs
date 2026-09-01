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
  injectedClient,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

// A two-project universe whose items are distinguishable per project, for
import {
  itemsCalls, scopeChips, twoProjectClient,
} from "./universe_ui_read_views_test_support.mjs";

test("Projects is an aggregate roster and each project opens its settings", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/projects";
  const root = documentNode.createElement("div");
  const requests = [];
  const roster = [
    {
      id: 1, slug: "yoke", name: "Yoke", emoji: "▤",
      github_repo: "acme/yoke", default_branch: "main",
      public_item_prefix: "YOK", in_flight_count: 3,
      ready_count: 2, blocked_count: 1, strategy_doc_count: 4,
      has_strategy: true,
    },
    {
      id: 2, slug: "notes", name: "Notes", emoji: "◇",
      github_repo: null, default_branch: "trunk",
      public_item_prefix: "NOT", in_flight_count: 0,
      ready_count: 1, blocked_count: 0, strategy_doc_count: 0,
      has_strategy: false,
    },
  ];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return {
          status: 200,
          envelope: { success: true, result: { name: "Yoke" } },
        };
      }
      if (request.function === "projects.list") {
        const rows = request.payload?.include_summary
          ? roster
          : roster.map(({ id, slug, name }) => ({ id, slug, name }));
        return {
          status: 200,
          envelope: { success: true, result: { rows } },
        };
      }
      if (request.function === "projects.get") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              row: {
                ...roster[0],
                github_sync_mode: "issue",
                created_at: "2026-07-01T12:00:00Z",
              },
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
    requests.find((request) => request.payload?.include_summary),
    { function: "projects.list", payload: { include_summary: true } },
  );
  assert.deepEqual(
    byClass(root, "metric").map((node) => node.children[0].textContent),
    ["2", "3", "3", "1", "4"],
  );
  assert.deepEqual(
    byClass(root, "row-link").map((node) => node.href),
    [
      "#/project?project=1",
      "https://github.com/acme/yoke",
      "#/project?project=2",
    ],
  );
  assert.equal(
    allNodes(root).find(
      (node) => node.tagName === "CODE" &&
        node.textContent ===
          "yoke projects create --slug <slug> --name <name> " +
            "--public-item-prefix <PREFIX>",
    ).textContent,
    "yoke projects create --slug <slug> --name <name> " +
      "--public-item-prefix <PREFIX>",
  );

  documentNode.defaultView.location.hash = "#/project?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.deepEqual(
    requests.find((request) => request.function === "projects.get"),
    { function: "projects.get", payload: { project: "1" } },
  );
  assert.deepEqual(
    byClass(root, "labelled-fact-label").map((node) => node.textContent),
    [
      "Project id", "Public item prefix", "Default branch",
      "GitHub repository", "GitHub sync", "Created",
    ],
  );
  const settingsText = allNodes(root)
    .map((node) => node.textContent || "").join(" ");
  for (const expected of ["YOK", "main", "acme/yoke", "issue"]) {
    assert.ok(settingsText.includes(expected), expected);
  }
  mounted.unmount();
});
test("every routed view opens with its prototype page head and scope summary", async (t) => {
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
    "Every harness session running against this universe, and what each one holds.",
  );
  // The head leads the content column. Sessions is a tabbed view, so its
  // project picker precedes the facet strip owned by the destination.
  const content = byClass(root, "content")[0];
  assert.ok(content.children[0].classList.contains("page-head"));
  const scopeIndex = content.children.findIndex(
    (child) => child.classList.contains("scope-bar"),
  );
  assert.ok(scopeIndex > 0);
  assert.ok(content.children[scopeIndex + 1].classList.contains("tab-bar"));

  documentNode.defaultView.location.hash = "#/items?project=1";
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  const itemsHead = byClass(root, "page-head")[0];
  assert.equal(byClass(itemsHead, "title")[0].textContent, "Items");
  assert.equal(byClass(itemsHead, "subtitle")[0].textContent,
    "scoped to Yoke · every durable piece of project work");
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
  const itemRow = (id, projectId, project) => ({
    id,
    public_ref: `YOK-${id}`,
    project_id: projectId,
    title: "t",
    workflow_id: "issue",
    workflow_version_id: 1,
    status: "idea",
    stage_label: "Idea",
    owner: "",
    claimed_by: null,
    project,
  });
  // Each bucket serves one row of a larger total, so the served counts and
  // the merged rows.length deliberately disagree.
  const servedByBucket = {
    1: { rows: [itemRow(11, 1, "alpha")], count: 3 },
    2: { rows: [itemRow(21, 2, "beta")], count: 4 },
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
      if (request.function === "items.overview.list") {
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
