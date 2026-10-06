import assert from "node:assert/strict";
import test from "node:test";
import { byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  classText, mountWorkflows, okEnvelope, workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";
import {
  buttonByText, checkboxRows, functionsCalled, mountPanel, toggle,
} from "./universe_ui_instruction_test_support.mjs";

test("workflows page lists every instruction above the tabs", async (t) => {
  const instructions = [
    {
      id: 1,
      content: "Cover the full scope of the work.\nSecond line ignored.",
      applies_to_all_workflows: true,
      applies_to_all_projects: true,
    },
    { id: 2, content: "Rally-only guidance", workflow_ids: ["rally"], project_ids: [1] },
    { id: 3, content: "Issue-only guidance", workflow_ids: ["issue"], project_ids: [] },
  ];
  const client = workflowsClient();
  const inner = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflow.execution_instruction.list") {
      client.requests.push(request);
      return okEnvelope({
        instructions: instructions.map((row) => ({ ...row })),
      });
    }
    return inner(request);
  };

  const { root, mounted } = await mountWorkflows(t, client);
  await settle();

  const host = byClass(root, "workflow-instructions-host")[0];
  const tabs = byClass(root, "tab-bar")[0];
  assert.ok(host && tabs, "host and tabs rendered");
  assert.equal(host.parentNode.children.indexOf(host) <
    host.parentNode.children.indexOf(tabs), true);
  assert.deepEqual(classText(root, "workflow-instruction-content"), [
    "Cover the full scope of the work.",
    "Rally-only guidance",
    "Issue-only guidance",
  ]);
  assert.deepEqual(classText(root, "workflow-instruction-reach"), [
    "applies to all workflows / all projects",
    "applies to 1 workflow / 1 project",
    "applies to 1 workflow / 0 projects",
  ]);
  mounted.unmount();
});

test("a new instruction starts unscoped instead of inheriting the open tab", async () => {
  const { host } = await mountPanel({
    workflows: [{ id: "dash", name: "Dash" }, { id: "issue", name: "Issue" }],
    projects: [{ id: 1, slug: "yoke" }],
  });

  assert.equal(byClass(host, "empty")[0].textContent, "No execution instructions.");
  buttonByText(host, "New instruction").dispatchEvent(new Event("click"));

  assert.equal(byClass(host, "instruction-editor").length, 1);
  assert.deepEqual(
    checkboxRows(host, "instruction-workflow-checkbox").map((row) => ({
      label: row.label,
      checked: row.input.checked,
    })),
    [
      { label: "Dash", checked: false },
      { label: "Issue", checked: false },
    ],
  );
  assert.equal(byClass(host, "instruction-all-workflows")[0].children[0].checked, false);
  assert.equal(byClass(host, "instruction-all-projects")[0].children[0].checked, false);
  assert.deepEqual(
    checkboxRows(host, "instruction-project-checkbox").map((row) => row.input.checked),
    [false],
  );
});

test("toggling All disables members but restores the prior selection", async () => {
  const { host, client } = await mountPanel({
    seed: [{
      id: 7,
      content: "Existing note",
      workflow_ids: ["dash"],
      project_ids: [1],
    }],
    workflows: [{ id: "dash", name: "Dash" }, { id: "issue", name: "Issue" }],
    projects: [{ id: 1, slug: "yoke" }, { id: 2, slug: "platform" }],
  });

  buttonByText(host, "Edit").dispatchEvent(new Event("click"));
  const workflowRows = () => checkboxRows(host, "instruction-workflow-checkbox");
  const projectRows = () => checkboxRows(host, "instruction-project-checkbox");
  const allWorkflows = byClass(host, "instruction-all-workflows")[0].children[0];
  const allProjects = byClass(host, "instruction-all-projects")[0].children[0];

  assert.deepEqual(workflowRows().map((row) => row.input.checked), [true, false]);
  assert.deepEqual(projectRows().map((row) => row.input.checked), [true, false]);
  toggle(allWorkflows, true);
  toggle(allProjects, true);
  assert.equal(workflowRows().every((row) => row.input.disabled === true), true);
  assert.deepEqual(workflowRows().map((row) => row.input.checked), [true, false]);
  toggle(allWorkflows, false);
  toggle(allProjects, false);
  assert.equal(workflowRows().every((row) => row.input.disabled === false), true);
  assert.deepEqual(projectRows().map((row) => row.input.checked), [true, false]);

  buttonByText(host, "Save instruction").dispatchEvent(new Event("click"));
  await settle();
  const scope = client.requests.find(
    (request) => request.function === "workflow.execution_instruction.set_scope",
  ).payload;
  assert.equal(scope.applies_to_all_workflows, false);
  assert.deepEqual(scope.workflow_ids, ["dash"]);
  assert.equal(scope.applies_to_all_projects, false);
  assert.deepEqual(scope.project_ids, [1]);
});

test("creating an instruction calls create then set_scope, then reloads", async () => {
  const { host, client } = await mountPanel({
    workflows: [{ id: "dash", name: "Dash" }],
    projects: [{ id: 1, slug: "yoke" }],
  });

  buttonByText(host, "New instruction").dispatchEvent(new Event("click"));
  const contentInput = byClass(host, "instruction-content-input")[0];
  contentInput.value = "Freshly authored guidance";
  contentInput.dispatchEvent(new Event("input"));
  toggle(checkboxRows(host, "instruction-workflow-checkbox")[0].input, true);
  buttonByText(host, "Create instruction").dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(functionsCalled(client), [
    "workflow.execution_instruction.list",
    "workflow.execution_instruction.create",
    "workflow.execution_instruction.set_scope",
    "workflow.execution_instruction.list",
  ]);
  assert.deepEqual(client.requests[1].payload, {
    content: "Freshly authored guidance",
    before_creation: true, on_every_read: true,
    when_entering_stage: false, stage_buckets: [],
  });
  const scope = client.requests[2].payload;
  assert.equal(scope.instruction_id, 900);
  assert.equal(scope.applies_to_all_workflows, false);
  assert.deepEqual(scope.workflow_ids, ["dash"]);
  assert.equal(scope.applies_to_all_projects, false);
  assert.deepEqual(scope.project_ids, []);
  assert.deepEqual(classText(host, "workflow-instruction-content"), [
    "Freshly authored guidance",
  ]);
});

test("editing an instruction calls update then set_scope with the new scope", async () => {
  const { host, client } = await mountPanel({
    seed: [{
      id: 42,
      content: "Old prose",
      workflow_ids: ["dash"],
      project_ids: [],
    }],
    workflows: [{ id: "dash", name: "Dash" }, { id: "issue", name: "Issue" }],
  });

  buttonByText(host, "Edit").dispatchEvent(new Event("click"));
  const contentInput = byClass(host, "instruction-content-input")[0];
  contentInput.value = "New prose";
  contentInput.dispatchEvent(new Event("input"));
  toggle(checkboxRows(host, "instruction-workflow-checkbox").find(
    (row) => row.label === "Issue",
  ).input, true);
  buttonByText(host, "Save instruction").dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(functionsCalled(client), [
    "workflow.execution_instruction.list",
    "workflow.execution_instruction.update",
    "workflow.execution_instruction.set_scope",
    "workflow.execution_instruction.list",
  ]);
  assert.deepEqual(client.requests[1].payload, {
    instruction_id: 42,
    content: "New prose",
    before_creation: true, on_every_read: true,
    when_entering_stage: false, stage_buckets: [],
  });
  assert.deepEqual(client.requests[2].payload.workflow_ids, ["dash", "issue"]);
});

test("deleting an instruction calls delete then returns to the empty state", async () => {
  const { host, client } = await mountPanel({
    seed: [{
      id: 55,
      content: "Doomed note",
      workflow_ids: ["dash"],
      project_ids: [],
    }],
    workflows: [{ id: "dash", name: "Dash" }],
  });

  buttonByText(host, "Edit").dispatchEvent(new Event("click"));
  buttonByText(host, "Delete").dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(functionsCalled(client), [
    "workflow.execution_instruction.list",
    "workflow.execution_instruction.delete",
    "workflow.execution_instruction.list",
  ]);
  assert.deepEqual(client.requests[1].payload, { instruction_id: 55 });
  assert.deepEqual(classText(host, "workflow-instruction-content"), []);
  assert.equal(byClass(host, "empty")[0].textContent, "No execution instructions.");
});
