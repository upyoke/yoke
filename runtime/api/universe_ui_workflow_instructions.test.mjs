import assert from "node:assert/strict";
import test from "node:test";

import {
  allNodes,
  byClass,
  FakeDocument,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  classText,
  mountWorkflows,
  okEnvelope,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";
import {
  workflowInstructionsPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/workflow_instructions_panel.js";

// A recording client for the five execution-instruction functions the panel
// and editor drive, backed by an in-memory store so a post-save reload shows
// the persisted scope the way the real proxy would. Editing lands two calls
// (content then scope); the store keeps both so the reload renders honestly.
function instructionsClient(seed = []) {
  const requests = [];
  const store = seed.map((row) => ({ ...row }));
  let nextId = 900;
  const find = (id) => store.find((row) => Number(row.id) === Number(id));
  return {
    requests,
    async call(request) {
      requests.push(request);
      const payload = request.payload || {};
      switch (request.function) {
        case "workflow.execution_instruction.list":
          return okEnvelope({ instructions: store.map((row) => ({ ...row })) });
        case "workflow.execution_instruction.create": {
          const id = nextId;
          nextId += 1;
          store.push({ id, content: payload.content });
          return okEnvelope({ instruction_id: id });
        }
        case "workflow.execution_instruction.update":
          find(payload.instruction_id).content = payload.content;
          return okEnvelope({});
        case "workflow.execution_instruction.set_scope": {
          const row = find(payload.instruction_id);
          row.applies_to_all_workflows = payload.applies_to_all_workflows;
          row.workflow_ids = payload.workflow_ids;
          row.applies_to_all_projects = payload.applies_to_all_projects;
          row.project_ids = payload.project_ids;
          return okEnvelope({});
        }
        case "workflow.execution_instruction.delete": {
          const index = store.findIndex(
            (row) => Number(row.id) === Number(payload.instruction_id),
          );
          if (index >= 0) store.splice(index, 1);
          return okEnvelope({});
        }
        default:
          throw new Error(`unexpected function ${request.function}`);
      }
    },
  };
}

function functionsCalled(client) {
  return client.requests.map((request) => request.function);
}

async function mountPanel({
  seed = [],
  workflow = { id: "dash", name: "Dash" },
  workflows = [{ id: "dash", name: "Dash" }],
  projects = [],
} = {}) {
  const documentNode = new FakeDocument();
  const client = instructionsClient(seed);
  const host = documentNode.createElement("div");
  host.appendChild(
    workflowInstructionsPanel(documentNode, workflow, client, {
      workflows,
      projects,
    }),
  );
  await settle();
  return { documentNode, client, host };
}

function buttonByText(host, text) {
  return allNodes(host).find(
    (node) => node.tagName === "BUTTON" && node.textContent === text,
  );
}

// The input of a labelled checkbox row is its first child; the label span is
// the second. Returns rows in render order.
function checkboxRows(host, className) {
  return byClass(host, className).map((row) => ({
    input: row.children[0],
    label: row.children[1].textContent,
  }));
}

function toggle(input, checked) {
  input.checked = checked;
  input.dispatchEvent(new Event("change"));
}

test("workflows page renders the instructions reaching the open workflow", async (t) => {
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

  // The panel renders its rows inside a workflow panel on the page, not on a
  // roster of its own — only the instructions reaching the open Rally workflow.
  const panel = byClass(root, "workflow-panel").find(
    (node) => byClass(node, "workflow-instruction-row").length > 0,
  );
  assert.ok(panel, "instructions panel rendered rows within the page");
  assert.deepEqual(classText(root, "workflow-instruction-content"), [
    "Cover the full scope of the work.",
    "Rally-only guidance",
  ]);
  assert.deepEqual(classText(root, "workflow-instruction-reach"), [
    "applies to all workflows / all projects",
    "applies to 1 workflow / 1 project",
  ]);
  assert.equal(
    byClass(root, "workflow-instruction-content").some(
      (node) => node.textContent === "Issue-only guidance",
    ),
    false,
  );
  mounted.unmount();
});

test("an empty panel invites a new instruction scoped to the open workflow", async () => {
  const { host } = await mountPanel({
    workflow: { id: "issue", name: "Issue" },
    workflows: [{ id: "dash", name: "Dash" }, { id: "issue", name: "Issue" }],
    projects: [{ id: 1, slug: "yoke" }],
  });

  assert.equal(byClass(host, "empty")[0].textContent, "No execution instructions apply to this workflow.");
  buttonByText(host, "New instruction").dispatchEvent(new Event("click"));

  assert.equal(byClass(host, "instruction-editor").length, 1);
  // A new instruction opens pre-scoped to the workflow being viewed.
  assert.deepEqual(
    checkboxRows(host, "instruction-workflow-checkbox").map((row) => ({
      label: row.label,
      checked: row.input.checked,
    })),
    [
      { label: "Dash", checked: false },
      { label: "Issue", checked: true },
    ],
  );
  assert.equal(
    byClass(host, "instruction-all-workflows")[0].children[0].checked,
    false,
  );
  assert.equal(
    byClass(host, "instruction-all-projects")[0].children[0].checked,
    false,
  );
  // No project is preselected for a brand-new instruction.
  assert.deepEqual(
    checkboxRows(host, "instruction-project-checkbox").map(
      (row) => row.input.checked,
    ),
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
    workflow: { id: "dash", name: "Dash" },
    workflows: [{ id: "dash", name: "Dash" }, { id: "issue", name: "Issue" }],
    projects: [{ id: 1, slug: "yoke" }, { id: 2, slug: "platform" }],
  });

  buttonByText(host, "Edit").dispatchEvent(new Event("click"));
  const workflowRows = () => checkboxRows(host, "instruction-workflow-checkbox");
  const projectRows = () => checkboxRows(host, "instruction-project-checkbox");
  const allWorkflows = byClass(host, "instruction-all-workflows")[0].children[0];
  const allProjects = byClass(host, "instruction-all-projects")[0].children[0];

  // Opens on the stored scope: dash + project 1, with members enabled.
  assert.deepEqual(workflowRows().map((row) => row.input.checked), [true, false]);
  assert.deepEqual(projectRows().map((row) => row.input.checked), [true, false]);
  assert.equal(workflowRows().every((row) => row.input.disabled === false), true);

  // Checking All disables the members without clearing their checked state.
  toggle(allWorkflows, true);
  toggle(allProjects, true);
  assert.equal(workflowRows().every((row) => row.input.disabled === true), true);
  assert.equal(projectRows().every((row) => row.input.disabled === true), true);
  assert.deepEqual(workflowRows().map((row) => row.input.checked), [true, false]);
  assert.deepEqual(projectRows().map((row) => row.input.checked), [true, false]);

  // Unchecking All re-enables the members with the original selection intact.
  toggle(allWorkflows, false);
  toggle(allProjects, false);
  assert.equal(workflowRows().every((row) => row.input.disabled === false), true);
  assert.deepEqual(workflowRows().map((row) => row.input.checked), [true, false]);
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
    workflow: { id: "dash", name: "Dash" },
    workflows: [{ id: "dash", name: "Dash" }],
    projects: [{ id: 1, slug: "yoke" }],
  });

  buttonByText(host, "New instruction").dispatchEvent(new Event("click"));
  const contentInput = byClass(host, "instruction-content-input")[0];
  contentInput.value = "Freshly authored guidance";
  contentInput.dispatchEvent(new Event("input"));
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
  });
  const scope = client.requests[2].payload;
  // The id the create returned threads straight into the scope call.
  assert.equal(scope.instruction_id, 900);
  assert.equal(scope.applies_to_all_workflows, false);
  assert.deepEqual(scope.workflow_ids, ["dash"]);
  assert.equal(scope.applies_to_all_projects, false);
  assert.deepEqual(scope.project_ids, []);
  // The reload shows the freshly created row, scoped to this workflow.
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
    workflow: { id: "dash", name: "Dash" },
    workflows: [{ id: "dash", name: "Dash" }, { id: "issue", name: "Issue" }],
    projects: [],
  });

  buttonByText(host, "Edit").dispatchEvent(new Event("click"));
  const contentInput = byClass(host, "instruction-content-input")[0];
  contentInput.value = "New prose";
  contentInput.dispatchEvent(new Event("input"));
  const issueInput = checkboxRows(host, "instruction-workflow-checkbox").find(
    (row) => row.label === "Issue",
  ).input;
  toggle(issueInput, true);
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
    workflow: { id: "dash", name: "Dash" },
    workflows: [{ id: "dash", name: "Dash" }],
    projects: [],
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
  assert.equal(byClass(host, "empty").length, 1);
});
