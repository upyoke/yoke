import assert from "node:assert/strict";
import test from "node:test";
import { renderNewItemView } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_new.js";
import { createProjectControls } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_app_shell_support.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { itemText } from "./universe_ui_items_test_support.mjs";

function setup() {
  const document = new FakeDocument(), root = document.createElement("div"), requests = [];
  const projects = [{ id: 7, slug: "acme", name: "Acme" }, { id: 9, slug: "other", name: "Other" }];
  const context = {
    document, projects: () => projects, isMounted: () => true, navigate: () => {},
    client: { async call(request) {
      requests.push(request);
      let result;
      if (request.function === "projects.list") result = { creation_scoped: true, rows: projects };
      else if (request.function === "workflows.definition.get") result = {
        workflows: [{ id: "dash", name: "Dash", definition: { entry_surfaces: ["web_form"], policies: {} } }],
        title_max_length: request.payload.project === "7" ? 12 : 100,
      };
      else if (request.function === "workflow.execution_instruction.resolve") result = {
        execution_instructions: [{ content: `Instructions for ${request.payload.project}` }],
      };
      else if (request.function === "items.create") result = { public_ref: "OTHER-1" };
      else result = { rows: [] };
      return { status: 200, envelope: { success: true, result } };
    } },
  };
  return { context, root, requests };
}

test("All requires a body project choice; switching keeps the draft and creation target", async () => {
  const { context, root, requests } = setup();
  renderNewItemView(context, root, "all");
  await settle();
  assert.equal(requests.filter((r) => r.function === "workflows.definition.get").length, 0);
  const selector = byClass(root, "item-project-select")[0];
  assert.equal(selector.value, "");
  selector.value = "9";
  selector.dispatchEvent(new Event("change"));
  await settle();
  allNodes(root).find((n) => n.tagName === "INPUT").value = "A long draft title";
  allNodes(root).find((n) => n.tagName === "TEXTAREA").value = "Keep this instruction";
  selector.value = "7";
  selector.dispatchEvent(new Event("change"));
  await settle();
  assert.equal(allNodes(root).find((n) => n.tagName === "INPUT").value, "A long draft title");
  assert.equal(allNodes(root).find((n) => n.tagName === "INPUT").maxLength, 12);
  assert.equal(allNodes(root).find((n) => n.tagName === "TEXTAREA").value, "Keep this instruction");
  assert.match(itemText(root), /Instructions for 7/);
  allNodes(root).find((n) => n.tagName === "FORM").dispatchEvent(new Event("submit"));
  assert.match(itemText(root), /12-character limit/);
  allNodes(root).find((n) => n.tagName === "INPUT").value = "Short title";
  allNodes(root).find((n) => n.tagName === "FORM").dispatchEvent(new Event("submit"));
  await settle();
  assert.equal(requests.find((r) => r.function === "items.create").payload.project, "acme");
});

test("New Item suppresses the top-navigation selector", () => {
  const { context } = setup();
  const controls = createProjectControls({ documentNode: context.document,
    entry: { id: "items", scope: "multi" }, route: { detail: "new" },
    scopeSelections: { notice: "" }, projects: context.projects(),
  });
  assert.equal(controls, null);
});

test("an older server cannot silently supply unfiltered creation projects", async () => {
  const { context, root } = setup();
  context.client.call = async () => ({ status: 200, envelope: { success: true, result: { rows: context.projects() } } });
  renderNewItemView(context, root, "7");
  await settle();
  assert.match(itemText(root), /Update the server/);
  assert.equal(allNodes(root).some((n) => n.tagName === "FORM"), false);
});
