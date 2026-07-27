import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemsView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import {
  markdownSection,
  withoutMarkdownSections,
} from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_primitives.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";

test("item narrative sections keep nested headings with their parent", () => {
  const source = [
    "Overview.",
    "",
    "## Acceptance Criteria",
    "- [ ] Parent check",
    "### Browser",
    "- [ ] Nested check",
    "",
    "## File Budget",
    "- `app.js`",
  ].join("\n");

  assert.match(markdownSection(source, "Acceptance Criteria"), /### Browser/);
  assert.doesNotMatch(
    markdownSection(source, "Acceptance Criteria"),
    /File Budget/,
  );
  const without = withoutMarkdownSections(
    source,
    ["Acceptance Criteria", "File Budget"],
  );
  assert.match(without, /Overview/);
  assert.doesNotMatch(without, /Nested check|app\.js/);
});

test("Items is one workflow roster with distinct owner and claim facts", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemsView(itemContext(documentNode, async (request) => {
    requests.push(request);
    return {
      status: 200,
      envelope: {
        success: true,
        result: {
          count: 2,
          rows: [
            {
              id: 41,
              public_ref: "ACM-12",
              project_id: 7,
              title: "Ship the direct fix",
              workflow_id: "dash",
              workflow_version_id: 3,
              status: "reviewing-implementation",
              stage_label: "Reviewing work",
              owner: "Rae",
              claimed_by: {
                actor_label: "build-system",
                session_id: "session-a",
              },
            },
            {
              id: 42,
              public_ref: "ACM-13",
              project_id: 7,
              title: "Plan the boundary",
              workflow_id: "epic",
              workflow_version_id: 2,
              status: "planned",
              stage_label: "Ready to plan",
              owner: "",
              claimed_by: null,
            },
          ],
        },
      },
    };
  }), root, "all");
  await settle();

  assert.deepEqual(requests, [{
    function: "items.overview.list",
    payload: {},
  }]);
  assert.equal(byClass(root, "item-workflow").length, 2);
  assert.equal(byClass(root, "item-roster-wrap").length, 1);
  assert.deepEqual(
    allNodes(byClass(root, "item-roster")[0])
      .filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    ["ID", "project", "Title", "Workflow", "Status", "Owner", "Claimed by"],
  );
  assert.deepEqual(
    byClass(root, "item-project").map((node) => node.textContent),
    ["acme", "acme"],
  );
  assert.match(itemText(root), /ACM-12/);
  assert.match(itemText(root), /Ship the direct fix/);
  assert.match(itemText(root), /Rae/);
  assert.match(itemText(root), /build-system/);
  assert.match(itemText(root), /unassigned/);
  assert.match(itemText(root), /Reviewing work/);
  assert.match(itemText(root), /Ready to plan/);
  assert.doesNotMatch(itemText(root), /reviewing-implementation/);
  assert.ok(!itemText(root).includes("priority"));
  const hrefs = byClass(root, "row-link").map((node) => node.href);
  assert.deepEqual(hrefs, [
    "#/items/ACM-12?project=7",
    "#/items/ACM-13?project=7",
  ]);
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 2");
  assert.equal(byClass(root, "item-action")[0].href, "#/items/new?project=7");
});

test("Items projects its scope copy and actions into the shared page head", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  let pageHead = null;
  renderItemsView(itemContext(documentNode, async () => ({
    status: 200,
    envelope: { success: true, result: { count: 0, rows: [] } },
  })), root, ["7"], {
    setPageHead(options) {
      pageHead = options;
    },
  });
  await settle();

  assert.equal(pageHead.title, "Items");
  assert.equal(
    pageHead.summary,
    "scoped to acme · every durable piece of project work",
  );
  assert.deepEqual(
    pageHead.actions.map((node) => node.textContent),
    ["Filter ▾", "New item"],
  );
  assert.equal(pageHead.actions[1].href, "#/items/new?project=7");
  assert.equal(byClass(root, "item-roster-toolbar").length, 0);
  assert.equal(
    byClass(root, "empty")[0].textContent,
    "No items match this view.",
  );
});

test("Items keeps the filter control mounted while its rows update", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  renderItemsView(itemContext(documentNode, async () => ({
    status: 200,
    envelope: {
      success: true,
      result: {
        count: 2,
        rows: [
          {
            public_ref: "ACM-12", project_id: 7, title: "Ship the fix",
            workflow_id: "dash", status: "new", stage_label: "Idea",
            owner: "", claimed_by: null,
          },
          {
            public_ref: "ACM-13", project_id: 7, title: "Plan the work",
            workflow_id: "epic", status: "planned", stage_label: "Ready to plan",
            owner: "", claimed_by: null,
          },
        ],
      },
    },
  })), root, "all");
  await settle();

  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Filter ▾",
  ).dispatchEvent(new Event("click"));
  const search = allNodes(root).find(
    (node) => node.tagName === "INPUT" && node.type === "search",
  );
  const workflow = allNodes(root).find(
    (node) => node.tagName === "SELECT" &&
      node.children[0]?.textContent === "All workflows",
  );
  const status = allNodes(root).find(
    (node) => node.tagName === "SELECT" &&
      node.children[0]?.textContent === "All statuses",
  );
  assert.deepEqual(
    workflow.children.map((node) => node.textContent),
    ["All workflows", "dash", "epic"],
  );
  assert.deepEqual(
    status.children.map((node) => node.textContent),
    ["All statuses", "Idea", "Ready to plan"],
  );
  workflow.value = "epic";
  workflow.dispatchEvent(new Event("change"));
  assert.equal(byClass(root, "item-roster-row").length, 1);
  assert.match(itemText(root), /Plan the work/);
  assert.doesNotMatch(itemText(root), /Ship the fix/);
  workflow.value = "";
  workflow.dispatchEvent(new Event("change"));
  search.value = "ship";
  search.dispatchEvent(new Event("input"));

  assert.ok(allNodes(root).includes(search));
  assert.equal(byClass(root, "item-roster-row").length, 1);
  assert.match(itemText(root), /Ship the fix/);
  assert.doesNotMatch(itemText(root), /Plan the work/);
});

test("Items rows retain native links and open from the row surface", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  renderItemsView(itemContext(documentNode, async () => ({
    status: 200,
    envelope: {
      success: true,
      result: {
        count: 1,
        rows: [{
          public_ref: "ACM-12", project_id: 7, title: "Ship the fix",
          workflow_id: "dash", status: "new", owner: "", claimed_by: null,
        }],
      },
    },
  })), root, "all");
  await settle();

  const row = byClass(root, "item-roster-row")[0];
  assert.equal(row.attributes.get("role"), "link");
  row.dispatchEvent(new Event("click"));
  assert.equal(
    documentNode.defaultView.location.hash,
    "#/items/ACM-12?project=7",
  );
  assert.equal(byClass(root, "row-link")[0].href, "#/items/ACM-12?project=7");
});

test("Items exposes a unified-read failure instead of substituting legacy UI", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemsView(itemContext(documentNode, async (request) => {
    requests.push(request);
    return {
      status: 503,
      envelope: {
        success: false,
        error: { message: "unified roster unavailable" },
      },
    };
  }), root, "all");
  await settle();

  assert.deepEqual(requests.map((request) => request.function), [
    "items.overview.list",
  ]);
  assert.match(itemText(root), /unified roster unavailable/);
  assert.equal(byClass(root, "item-roster-row").length, 0);
});
