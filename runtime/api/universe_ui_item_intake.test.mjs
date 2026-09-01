import assert from "node:assert/strict";
import test from "node:test";

import {
  renderNewItemView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_new.js";
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

test("New item derives web-fileability and settings from the definition", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const workflows = [
    {
      id: "issue",
      name: "Issue",
      definition: { entry_surfaces: ["harness_skill"], policies: {} },
    },
    {
      id: "dash",
      name: "Dash",
      definition: {
        entry_surfaces: ["web_form", "cli", "harness_skill", "promotion"],
        stages: [{
          id: "reviewing-implementation",
          label: "Reviewing work",
        }],
        policies: {
          item_posture_allowlist: [
            "verification", "file_budget", "path_claims",
            "path_survey",
            "approval_on_done", "deployment",
          ],
        },
      },
    },
    {
      id: "task",
      name: "Task",
      definition: {
        entry_surfaces: ["web_form", "cli", "harness_skill", "promotion"],
        policies: {
          item_posture_allowlist: [],
          path_survey: "optional",
          worktrees: "none",
          delivery: "merge_free",
        },
      },
    },
  ];
  const requests = [];
  renderNewItemView(itemContext(documentNode, async (request) => {
    requests.push(request);
    const result = request.function === "workflows.definition.get"
      ? { workflows }
      : request.function === "qa.plan.list"
        ? { rows: [{ id: 3, slug: "browser-close" }] }
        : { rows: [{ id: "browser-inspection", name: "Browser inspection" }] };
    return { status: 200, envelope: { success: true, result } };
  }), root, "7");
  await settle();

  const rendered = itemText(root);
  assert.match(rendered, /New Dash/);
  assert.match(rendered, /Dash and Task can be filed from the web/);
  assert.match(rendered, /Issue is filed in a harness \(\/yoke idea\)/);
  assert.match(rendered, /Title/);
  assert.match(rendered, /Instruction/);
  assert.match(rendered, /Verification/);
  assert.match(rendered, /File Budget/);
  assert.match(rendered, /Path claims/);
  assert.match(rendered, /Path survey/);
  assert.match(rendered, /Approval on done/);
  assert.match(rendered, /Deploy after merge/);
  assert.deepEqual(
    byClass(root, "item-project-value").map((node) => node.textContent),
    ["🐜 acme"],
  );
  assert.equal(byClass(root, "item-setting-row").length, 6);
  assert.deepEqual(
    byClass(root, "item-workflow-options")[0].children.map(
      (node) => node.textContent,
    ),
    ["Dash", "Task"],
  );
  assert.deepEqual(requests.map((request) => request.function), [
    "workflows.definition.get",
    "qa.plan.list",
    "qa.method.list",
  ]);

  const verification = byClass(root, "item-setting-row")[0];
  assert.equal(
    byClass(verification, "item-button")[0].attributes.get("aria-pressed"),
    "false",
  );
  byClass(verification, "item-button")[0].dispatchEvent(new Event("click"));
  const enabled = itemText(root);
  assert.match(enabled, /plan · browser-close/);
  assert.match(enabled, /ad hoc · Browser inspection/);
  assert.match(enabled, /runs at reviewing-implementation/);
  assert.equal(
    byClass(byClass(root, "item-setting-row")[0], "item-button")[0]
      .attributes.get("aria-pressed"),
    "true",
  );
  const textarea = allNodes(root).find((node) => node.tagName === "TEXTAREA");
  assert.equal(textarea.rows, 3);
  assert.equal(byClass(root, "item-form-help")[0].parentNode.tagName, "LABEL");

  byClass(root, "item-workflow-options")[0].children[1]
    .dispatchEvent(new Event("click"));
  const taskView = itemText(root);
  assert.match(taskView, /New Task/);
  assert.match(taskView, /complete laneless, merge-free instruction/);
  assert.doesNotMatch(taskView, /Verification|Approval on done|Deploy after merge/);
  assert.equal(byClass(root, "item-setting-row").length, 0);
});

test("New item submits one atomic create and routes to the public ref", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  let destination = null;
  const viewContext = itemContext(documentNode, async (request) => {
    requests.push(request);
    if (request.function === "workflows.definition.get") {
      return {
        status: 200,
        envelope: {
          success: true,
          result: {
            workflows: [{
              id: "dash",
              name: "Dash",
              definition: {
                entry_surfaces: ["web_form"],
                policies: {
                  item_posture_allowlist: [
                    "verification", "file_budget", "path_claims",
                    "path_survey",
                    "approval_on_done", "deployment",
                  ],
                },
              },
            }],
          },
        },
      };
    }
    if (request.function === "qa.plan.list") {
      return {
        status: 200,
        envelope: {
          success: true,
          result: { rows: [{ id: 3, slug: "smoke" }] },
        },
      };
    }
    if (request.function === "qa.method.list") {
      return {
        status: 200,
        envelope: { success: true, result: { rows: [] } },
      };
    }
    return {
      status: 200,
      envelope: { success: true, result: { public_ref: "ACM-23" } },
    };
  });
  viewContext.navigate = (route) => {
    destination = route;
  };
  renderNewItemView(viewContext, root, "7");
  await settle();

  byClass(byClass(root, "item-setting-row")[0], "item-button")[0]
    .dispatchEvent(new Event("click"));
  byClass(byClass(root, "item-setting-row")[1], "item-button")[0]
    .dispatchEvent(new Event("click"));
  byClass(byClass(root, "item-setting-row")[2], "item-button")[0]
    .dispatchEvent(new Event("click"));
  byClass(byClass(root, "item-setting-row")[4], "item-button")[0]
    .dispatchEvent(new Event("click"));
  byClass(byClass(root, "item-setting-row")[5], "item-button")[0]
    .dispatchEvent(new Event("click"));
  const input = allNodes(root).find((node) => node.tagName === "INPUT");
  const textarea = allNodes(root).find((node) => node.tagName === "TEXTAREA");
  input.value = "Fix the footer";
  textarea.value = "Correct it and verify every link.";
  allNodes(root).find((node) => node.tagName === "FORM")
    .dispatchEvent(new Event("submit"));
  await settle();

  const create = requests.find((request) => request.function === "items.create");
  assert.deepEqual(create.payload, {
    title: "Fix the footer",
    instruction: "Correct it and verify every link.",
    project: "acme",
    workflow: "dash",
    entry_surface: "web_form",
    workflow_posture: {
      verification: { kind: "plan", plan_id: 3 },
      file_budget: true,
      path_claims: true,
      approval_on_done: true,
      deployment: true,
    },
  });
  assert.equal(destination, "#/items/23?project=7");
});

test("New item files Task through the typed web surface without gate posture", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderNewItemView(itemContext(documentNode, async (request) => {
    requests.push(request);
    const result = request.function === "workflows.definition.get"
      ? {
        workflows: [{
          id: "task",
          name: "Task",
          definition: {
            entry_surfaces: ["web_form", "cli", "harness_skill", "promotion"],
            policies: {
              item_posture_allowlist: [],
              path_survey: "optional",
              worktrees: "none",
              delivery: "merge_free",
            },
          },
        }],
      }
      : request.function === "items.create"
        ? { public_ref: "ACM-31" }
        : { rows: [] };
    return { status: 200, envelope: { success: true, result } };
  }), root, "7");
  await settle();

  assert.match(itemText(root), /New Task/);
  assert.equal(byClass(root, "item-setting-row").length, 0);
  const input = allNodes(root).find((node) => node.tagName === "INPUT");
  const textarea = allNodes(root).find((node) => node.tagName === "TEXTAREA");
  input.value = "Refresh inventory";
  textarea.value = "Refresh the local inventory file.";
  allNodes(root).find((node) => node.tagName === "FORM")
    .dispatchEvent(new Event("submit"));
  await settle();

  const create = requests.find((request) => request.function === "items.create");
  assert.deepEqual(create.payload, {
    title: "Refresh inventory",
    instruction: "Refresh the local inventory file.",
    project: "acme",
    workflow: "task",
    entry_surface: "web_form",
    workflow_posture: {},
  });
  assert.match(itemText(root), /Created ACM-31/);
});
