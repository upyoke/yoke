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
// exercising the all/one/some scope picker end to end.
function twoProjectClient() {
  const requests = [];
  const itemRow = (id, title, project) => ({
    id, title, type: "issue", status: "idea", priority: "medium",
    blocked: "0", blocked_reason: "", project,
  });
  const rowsByProject = {
    1: [itemRow(11, "alpha item", "alpha")],
    2: [itemRow(21, "beta item", "beta")],
  };
  return {
    requests,
    async call(request) {
      requests.push(request);
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
        const bucket = request.payload.project;
        const rows = bucket === undefined
          ? [...rowsByProject[1], ...rowsByProject[2]]
          : rowsByProject[bucket] || [];
        return { status: 200, envelope: { success: true, result: { rows } } };
      }
      if (request.function === "strategy.doc.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              docs: [{
                slug: `PLAN-${request.target.project_id}`,
                title: "plan", archived: false,
              }],
            },
          },
        };
      }
      if (request.function === "events.query.run") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

function scopeChips(root) {
  return byClass(root, "scope-chip");
}

function itemsCalls(client) {
  return client.requests.filter(
    (request) => request.function === "items.list.run",
  );
}

test("the actor chip names the viewer, and is absent when nobody does", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const mountWith = (currentActor) => {
    const documentNode = new FakeDocument();
    const root = documentNode.createElement("div");
    const mounted = mountUniverseApp(root, {
      client: injectedClient(),
      ...(currentActor ? { currentActor } : {}),
    });
    const chip = allNodes(root).find(
      (node) => node.classList && node.classList.contains("actor-chip"),
    );
    const text = chip
      ? allNodes(chip).map((node) => node.textContent || "").filter(Boolean)
      : null;
    mounted.unmount();
    return text;
  };

  assert.deepEqual(mountWith({ id: 2, kind: "human", label: "Ben" }), ["Ben"]);
  assert.deepEqual(mountWith({ id: 2, kind: "human" }), ["actor 2"]);
  assert.deepEqual(
    mountWith({ id: 3, kind: "system", systemComponent: "skill-simulate" }),
    ["actor 3", "skill-simulate"],
  );
  assert.equal(mountWith(null), null);
});

test("an epic's detail carries its tasks; an issue's does not", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const drillInto = async (type) => {
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.hash = "#/items/7?project=1";
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
        if (request.function === "items.get.run") {
          return {
            status: 200,
            envelope: {
              success: true,
              result: {
                item_id: 7,
                fields: {
                  id: "7", type, status: "planned", title: "t", body: "# Spec",
                },
              },
            },
          };
        }
        if (request.function === "epic_tasks.list.run") {
          return {
            status: 200,
            envelope: {
              success: true,
              result: {
                epic_id: 7,
                tasks: [{ task_num: 1, title: "first", status: "done" }],
              },
            },
          };
        }
        throw new Error(`unexpected function ${request.function}`);
      },
    };
    const mounted = mountUniverseApp(root, { client });
    await settle();
    const text = allNodes(root).map((node) => node.textContent || "").join(" ");
    const detailRequest = requests.find(
      (request) => request.function === "items.get.run",
    );
    const result = {
      askedForTasks: requests.some(
        (request) => request.function === "epic_tasks.list.run",
      ),
      target: detailRequest.target,
      showsTask: text.includes("first"),
    };
    mounted.unmount();
    return result;
  };

  const epic = await drillInto("epic");
  assert.deepEqual(epic.target, {
    kind: "item", item_ref: "7", project_id: "1",
  });
  assert.equal(epic.askedForTasks, true);
  assert.equal(epic.showsTask, true);

  const issue = await drillInto("issue");
  assert.equal(issue.askedForTasks, false);
});

test("an unblocked item reports no blocking reason", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/items";
  const root = documentNode.createElement("div");
  let itemsRequest = null;
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, slug: "yoke", name: "Yoke" }] } } };
      }
      if (request.function === "items.list.run") {
        itemsRequest = request;
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [
                { id: 1, title: "runs", type: "issue", status: "idea", priority: "medium", blocked: "0", blocked_reason: "", project: "yoke" },
                { id: 2, title: "waits", type: "epic", status: "idea", priority: "high", blocked: "1", blocked_reason: "upstream schema", project: "yoke" },
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

  // The "all" default reads unfiltered and labels each row's project.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "1", "yoke", "issue", "runs", "idea", "medium", "",
    "2", "yoke", "epic", "waits", "idea", "high", "upstream schema",
  ]);
  // The drill-in carries the row's own project id, mapped from its slug.
  const rowLinks = allNodes(root)
    .filter((node) => node.classList && node.classList.contains("row-link"))
    .map((node) => node.href);
  assert.deepEqual(rowLinks, ["#/items/1?project=1", "#/items/2?project=1"]);
  assert.ok(itemsRequest.payload.fields.includes("type"));
  assert.ok(itemsRequest.payload.fields.includes("blocked_reason"));
  assert.ok(itemsRequest.payload.fields.includes("project"));
  assert.ok(!("project" in itemsRequest.payload));
  mounted.unmount();
});

test("Ouroboros reads observations and keeps review state visible", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/ouroboros?project=1";
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
      if (request.function === "ouroboros.entry.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              entries: [
                { timestamp: "now", category: "observation", agent: "tester", context: "open", reviewed_at: null },
                { timestamp: "then", category: "failed", agent: "doctor", context: "closed", reviewed_at: "later" },
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
    requests.find((request) => request.function === "ouroboros.entry.list"),
    { function: "ouroboros.entry.list", payload: { project: "1" } },
  );
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "now", "observation", "tester", "open", "",
    "then", "failed", "doctor", "closed", "later",
  ]);
  mounted.unmount();
});

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
  mounted.unmount();
});

test("a multi view defaults to the whole universe: All chip on, unfiltered read", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/items";
  const root = documentNode.createElement("div");
  const client = twoProjectClient();

  const mounted = mountUniverseApp(root, { client });
  await settle();

  const chips = scopeChips(root);
  assert.deepEqual(
    chips.map((chip) => chip.textContent), ["All", "Alpha", "Beta"],
  );
  assert.deepEqual(
    chips.map((chip) => chip.classList.contains("on")),
    [true, false, false],
  );
  assert.equal(byClass(root, "scope-label")[0].textContent, "Projects");
  assert.equal(
    byClass(root, "scope-hint")[0].textContent,
    "all / one / some · this screen remembers its own",
  );
  // "all" is one unfiltered call, and the default writes no query param.
  assert.deepEqual(
    itemsCalls(client).map((request) => request.payload.project), [undefined],
  );
  assert.equal(documentNode.defaultView.location.hash, "#/items");
  mounted.unmount();
});

test("chips narrow to one, widen to a pair, and empty back out to All", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/items";
  const root = documentNode.createElement("div");
  const client = twoProjectClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();

  const click = async (label) => {
    const before = client.requests.length;
    scopeChips(root).find((chip) => chip.textContent === label)
      .dispatchEvent(new Event("click"));
    await settle();
    return client.requests.slice(before)
      .filter((request) => request.function === "items.list.run");
  };

  // One project: the read carries it and the hash names it.
  const narrowed = await click("Alpha");
  assert.equal(documentNode.defaultView.location.hash, "#/items?project=1");
  assert.deepEqual(narrowed.map((request) => request.payload.project), ["1"]);
  assert.deepEqual(
    scopeChips(root).map((chip) => chip.classList.contains("on")),
    [false, true, false],
  );
  // Exactly one project needs no project column.
  assert.ok(!allNodes(root).some(
    (node) => node.tagName === "TH" && node.textContent === "project",
  ));

  // A second chip widens to the pair: one read per member, rows merged in
  // call order, each labelled with its own project.
  const paired = await click("Beta");
  assert.equal(documentNode.defaultView.location.hash, "#/items?project=1,2");
  assert.deepEqual(paired.map((request) => request.payload.project), ["1", "2"]);
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "11", "alpha", "issue", "alpha item", "idea", "medium", "",
    "21", "beta", "issue", "beta item", "idea", "medium", "",
  ]);
  // Each row's drill-in carries that row's own project.
  assert.deepEqual(
    allNodes(root)
      .filter((node) => node.classList && node.classList.contains("row-link"))
      .map((node) => node.href),
    ["#/items/11?project=1", "#/items/21?project=2"],
  );

  // Removing members one at a time: the last removal returns to "all",
  // whose read omits the project filter and whose route has no query.
  await click("Alpha");
  assert.equal(documentNode.defaultView.location.hash, "#/items?project=2");
  const widened = await click("Beta");
  assert.equal(documentNode.defaultView.location.hash, "#/items");
  assert.deepEqual(widened.map((request) => request.payload.project), [undefined]);
  assert.deepEqual(
    scopeChips(root).map((chip) => chip.classList.contains("on")),
    [true, false, false],
  );
  mounted.unmount();
});

test("strategy at All fans out one call per roster project", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/strategy";
  const root = documentNode.createElement("div");
  const client = twoProjectClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.deepEqual(
    client.requests
      .filter((request) => request.function === "strategy.doc.list")
      .map((request) => request.target),
    [
      { kind: "global", project_id: "1" },
      { kind: "global", project_id: "2" },
    ],
  );
  // Rows from every bucket render, labelled by the requesting project.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "PLAN-1", "alpha", "plan", "active",
    "PLAN-2", "beta", "plan", "active",
  ]);
  mounted.unmount();
});

test("each screen remembers its own scope across nav round trips", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.location.hash = "#/items?project=2";
  const root = documentNode.createElement("div");
  const client = twoProjectClient();
  const mounted = mountUniverseApp(root, { client });
  await settle();

  const navigate = async (hash) => {
    windowNode.location.hash = hash;
    windowNode.dispatchEvent(new Event("hashchange"));
    await settle();
  };

  await navigate("#/events");
  const itemsLink = byClass(root, "nav-link").find((link) =>
    allNodes(link).some(
      (node) => node.classList.contains("txt") &&
        node.textContent === "Items",
    ));
  // The nav link back carries the scope the screen last held...
  assert.equal(itemsLink.href, "#/items?project=2");

  // ...and following it restores that scope's read.
  await navigate(itemsLink.href);
  const lastItems = itemsCalls(client).at(-1);
  assert.equal(lastItems.payload.project, "2");
  mounted.unmount();
});

test("a single-scope picker offers radio chips and no All chip", () => {
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  const selections = new Map();
  const rendered = [];
  const bar = createScopePicker({
    documentNode,
    entry: navEntry("workflows"),
    scope: "1",
    projects: [
      { id: 1, slug: "alpha", name: "Alpha" },
      { id: 2, slug: "beta", name: "Beta" },
    ],
    renderRoute: () => rendered.push(true),
    scopeSelections: selections,
    segment: null,
    windowNode,
  });

  assert.equal(byClass(bar, "scope-label")[0].textContent, "Project");
  assert.equal(
    byClass(bar, "scope-hint")[0].textContent,
    "one project — this screen configures a single target",
  );
  const chips = byClass(bar, "scope-chip");
  assert.deepEqual(chips.map((chip) => chip.textContent), ["Alpha", "Beta"]);
  assert.deepEqual(
    chips.map((chip) => chip.classList.contains("on")), [true, false],
  );

  // Radio semantics: a click selects exactly that project.
  chips[1].dispatchEvent(new Event("click"));
  assert.equal(selections.get("workflows"), "2");
  assert.equal(windowNode.location.hash, "#/workflows?project=2");
  assert.equal(rendered.length, 1);
});

test("a multi view still reads an empty universe, unfiltered", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/items";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
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

  // An unfiltered read over an empty universe is honest: the view renders
  // its own empty table rather than a "no projects" panel.
  assert.ok(requests.some(
    (request) => request.function === "items.list.run" &&
      !("project" in request.payload),
  ));
  const text = allNodes(root)
    .map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("no items yet"));
  assert.ok(!text.includes("no projects yet"));
  mounted.unmount();
});

test("a drill-in route survives the round trip and never outlives its view", () => {
  assert.deepEqual(parseUniverseRoute("#/items/42?project=3"), {
    view: "items", tab: null, detail: "42", project: "3",
  });
  assert.equal(buildUniverseRoute("items", "3", "42"), "#/items/42?project=3");
  const odd = "YOK 7/a";
  assert.equal(
    parseUniverseRoute(buildUniverseRoute("items", "3", odd)).detail, odd,
  );
  assert.deepEqual(parseUniverseRoute("#/unknown/42"), {
    view: "overview", tab: null, detail: null, project: null,
  });
  assert.equal(buildUniverseRoute("unknown", null, "42"), "#/overview");
});
