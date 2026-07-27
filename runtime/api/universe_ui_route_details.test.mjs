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

test("a strategy doc drill-in reads the body through strategy.surface.get", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/strategy/PLAN-1?project=1";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
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
            result: { rows: [{ id: 1, slug: "alpha", name: "Alpha" }] },
          },
        };
      }
      if (request.function === "strategy.surface.get") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              project_slug: "alpha",
              document: {
                slug: "PLAN-1",
                content: "# The plan\n\nOne spine.",
                updated_at: "today",
                bytes: 23,
                current_revision: 1,
                revisions: [],
                archived: false,
                execution_claim: null,
                review_requests: [],
                pending_review_count: 0,
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

  // The doc read resolves its project through the target, slug in payload.
  const docRequest = requests.find(
    (request) => request.function === "strategy.surface.get",
  );
  assert.deepEqual(docRequest.target, { kind: "global", project_id: "1" });
  assert.deepEqual(docRequest.payload, { slug: "PLAN-1" });

  // The served body renders for review beneath the breadcrumb and its own
  // shared detail page head.
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("The plan"));
  assert.ok(text.includes("One spine."));
  assert.ok(text.includes("State & actions"));
  assert.equal(byClass(root, "breadcrumb").length, 1);
  assert.equal(byClass(root, "page-head").length, 1);
  assert.equal(byClass(root, "page-head")[0].children[0].className, "h item-detail-heading-copy");
  assert.equal(byClass(root, "page-head")[0].children[0].children[0].className, "title");
  mounted.unmount();
});

test("events at All merge newest-first across buckets and name their source", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/events";
  const root = documentNode.createElement("div");
  const rowsByProject = {
    // Bucket order alone would render alpha's block before beta's newer
    // row; the merged stream must interleave by timestamp instead.
    1: [
      {
        created_at: "2026-07-20T10:00:00Z",
        event_name: "Old",
        event_kind: "system",
        category: "system",
        severity: "INFO",
        project: "alpha",
        target_label: "Universe",
        source_label: "actor 2",
      },
      {
        created_at: "2026-07-20T12:00:00.500Z",
        event_name: "Newest",
        event_kind: "system",
        category: "system",
        severity: "INFO",
        project: "alpha",
        target_label: "Universe",
        source_label: "cli",
      },
    ],
    2: [
      {
        created_at: "2026-07-20T11:00:00Z",
        event_name: "Middle",
        event_kind: "lifecycle",
        category: "workflow",
        severity: "INFO",
        project: "beta",
        target_kind: "item",
        target_label: "YOK-7",
        target_project_id: 2,
        context_label: "Lifecycle advanced",
        source_label: "actor 170",
      },
    ],
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
      if (request.function === "events.query.run") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: { rows: rowsByProject[request.payload.project] || [] },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.deepEqual(
    byClass(root, "event-name").map((node) => node.textContent),
    ["Newest", "Middle", "Old"],
  );
  assert.deepEqual(
    byClass(root, "event-category").map((node) => node.textContent),
    ["System", "Workflow", "System"],
  );
  assert.deepEqual(
    byClass(root, "event-filter").map((node) => node.textContent),
    ["All · 3", "Workflow · 1", "System · 2"],
  );
  const timelineText = byClass(root, "event-timeline")[0].children
    .map((node) => allNodes(node).map((part) => part.textContent).join(" "));
  assert.ok(timelineText[0].includes("Source cli"));
  assert.ok(timelineText[1].includes("Lifecycle advanced"));
  assert.ok(timelineText[1].includes("Source actor 170"));
  assert.ok(timelineText[2].includes("Source actor 2"));
  assert.equal(
    byClass(root, "event-card")[1]
      .children.flatMap(allNodes)
      .find((node) => node.classList.contains("row-link")).href,
    "#/items/7?project=2",
  );

  // Filters are local: narrowing the rendered stream does not make another
  // authority read, and the selected chip carries the on state.
  const workflowFilter = byClass(root, "event-filter")[1];
  workflowFilter.dispatchEvent(new Event("click"));
  assert.deepEqual(
    byClass(root, "event-name").map((node) => node.textContent),
    ["Middle"],
  );
  assert.ok(workflowFilter.classList.contains("on"));
  assert.equal(workflowFilter.attributes.get("aria-pressed"), "true");
  assert.equal(
    byClass(root, "event-filter")[0].attributes.get("aria-pressed"),
    "false",
  );
  mounted.unmount();
});
