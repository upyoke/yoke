import assert from "node:assert/strict";
import test from "node:test";

import {
  renderExecutionInstructionsView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_execution_instructions.js";
import {
  workflowInstructionsPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/workflow_instructions_panel.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

function instructionFixtures() {
  return [
    {
      id: 3,
      title: "Prefer impacted test selection",
      content: "Run the impacted selection before the full gate.",
      applies_to_all_projects: true,
      ordering: 10,
      status: "active",
      workflow_ids: ["dash", "issue", "epic"],
      project_ids: [],
    },
    {
      id: 4,
      title: "Detached from every workflow",
      content: "Matches nothing until a workflow is selected.",
      applies_to_all_projects: false,
      ordering: 20,
      status: "disabled",
      workflow_ids: [],
      project_ids: [2],
    },
  ];
}

function workflowRows() {
  return [
    { id: "dash", name: "Dash" },
    { id: "issue", name: "Issue" },
  ];
}

function instructionsClient({
  instructions = instructionFixtures(),
  workflows = workflowRows(),
} = {}) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "workflow.execution_instruction.list") {
        return okEnvelope({ instructions });
      }
      if (request.function === "workflows.definition.get") {
        return okEnvelope({ workflows });
      }
      if (request.function === "workflow.execution_instruction.create") {
        return okEnvelope({ instruction_id: 7 });
      }
      for (const operation of ["update", "set_scope", "delete"]) {
        if (
          request.function === `workflow.execution_instruction.${operation}`
        ) {
          return okEnvelope({
            instruction_id: request.payload.instruction_id,
          });
        }
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

function context(documentNode, client) {
  return {
    document: documentNode,
    client,
    isMounted: () => true,
    projects: () => [
      { id: 1, slug: "yoke", name: "Yoke" },
      { id: 2, slug: "notes", name: "Notes" },
    ],
  };
}

function checkboxInput(row) {
  return row.children[0];
}

test("the roster lists each instruction's scope and marks inert ones", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = instructionsClient();

  renderExecutionInstructionsView(context(documentNode, client), main);
  await settle();

  assert.equal(
    client.requests[0].function, "workflow.execution_instruction.list",
  );
  assert.equal(client.requests[1].function, "workflows.definition.get");
  const rows = byClass(main, "instruction-row");
  assert.equal(rows.length, 2);
  assert.deepEqual(
    byClass(main, "instruction-row-title").map((node) => node.textContent),
    ["Prefer impacted test selection", "Detached from every workflow"],
  );
  assert.deepEqual(
    byClass(main, "instruction-row-scope").map((node) => node.textContent),
    ["3 workflows / All projects", "0 workflows / 1 project"],
  );
  // Only the workflow-less instruction wears the inert badge: it matches
  // nothing, and the roster says so instead of letting it look configured.
  const badges = byClass(main, "instruction-inert-badge");
  assert.equal(badges.length, 1);
  assert.equal(badges[0].textContent, "inert");
  assert.equal(rows[0].contains(badges[0]), false);
  assert.equal(rows[1].contains(badges[0]), true);
  assert.deepEqual(
    allNodes(main)
      .map((node) => node.attributes.get("data-state"))
      .filter(Boolean),
    ["active", "disabled"],
  );
});

test("the editor's All projects checkbox disables members without erasing them", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = instructionsClient();

  renderExecutionInstructionsView(context(documentNode, client), main);
  await settle();
  byClass(main, "instruction-row")[1].dispatchEvent(new Event("click"));

  const workflowBoxes = byClass(main, "instruction-workflow-checkbox");
  assert.deepEqual(
    workflowBoxes.map((row) => row.children[1].textContent),
    ["Dash", "Issue"],
  );
  const allProjects = checkboxInput(
    byClass(main, "instruction-all-projects")[0],
  );
  assert.equal(allProjects.checked, false);
  const memberInputs = byClass(main, "instruction-project-checkbox")
    .map(checkboxInput);
  assert.equal(memberInputs.length, 2);
  assert.deepEqual(memberInputs.map((input) => input.disabled), [false, false]);
  assert.deepEqual(memberInputs.map((input) => input.checked), [false, true]);

  allProjects.checked = true;
  allProjects.dispatchEvent(new Event("change"));
  assert.deepEqual(memberInputs.map((input) => input.disabled), [true, true]);
  // The members keep their checked state visibly unchanged while disabled.
  assert.deepEqual(memberInputs.map((input) => input.checked), [false, true]);

  allProjects.checked = false;
  allProjects.dispatchEvent(new Event("change"));
  assert.deepEqual(memberInputs.map((input) => input.disabled), [false, false]);
});

test("saving a new instruction issues create then set_scope", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = instructionsClient();

  renderExecutionInstructionsView(context(documentNode, client), main);
  await settle();
  allNodes(main)
    .find((node) => node.textContent === "New instruction")
    .dispatchEvent(new Event("click"));

  const title = byClass(main, "instruction-title-input")[0];
  title.value = "Name the failing test first";
  title.dispatchEvent(new Event("input"));
  const content = byClass(main, "instruction-content-input")[0];
  content.value = "Quote the failing test before proposing a fix.";
  content.dispatchEvent(new Event("input"));
  const dashBox = checkboxInput(
    byClass(main, "instruction-workflow-checkbox")[0],
  );
  dashBox.checked = true;
  dashBox.dispatchEvent(new Event("change"));
  const allProjects = checkboxInput(
    byClass(main, "instruction-all-projects")[0],
  );
  allProjects.checked = true;
  allProjects.dispatchEvent(new Event("change"));

  allNodes(main)
    .find((node) => node.textContent === "Create instruction")
    .dispatchEvent(new Event("click"));
  await settle();

  const created = client.requests.find(
    (request) =>
      request.function === "workflow.execution_instruction.create",
  );
  assert.deepEqual(created.payload, {
    title: "Name the failing test first",
    content: "Quote the failing test before proposing a fix.",
    ordering: 0,
    status: "active",
  });
  const scoped = client.requests.find(
    (request) =>
      request.function === "workflow.execution_instruction.set_scope",
  );
  assert.deepEqual(scoped.payload, {
    instruction_id: 7,
    workflow_ids: ["dash"],
    applies_to_all_projects: true,
    project_ids: [],
  });
  // The save lands back on the reloaded roster.
  assert.equal(byClass(main, "instruction-row").length, 2);
});

test("the workflow detail panel shows resolved instructions with their reach", async () => {
  const documentNode = new FakeDocument();
  const client = instructionsClient({
    instructions: [
      ...instructionFixtures(),
      {
        id: 5,
        title: "Disabled for dash",
        applies_to_all_projects: false,
        status: "disabled",
        workflow_ids: ["dash"],
        project_ids: [1],
      },
      {
        id: 6,
        title: "Issue-only guidance",
        applies_to_all_projects: false,
        status: "active",
        workflow_ids: ["issue"],
        project_ids: [1],
      },
    ],
  });

  const panel = workflowInstructionsPanel(
    documentNode, { id: "dash" }, client,
  );
  await settle();

  assert.deepEqual(
    allNodes(panel)
      .filter((node) => node.tagName === "H2")
      .map((node) => node.textContent),
    ["Execution instructions"],
  );
  // Only active instructions naming this workflow resolve here.
  const titles = byClass(panel, "workflow-instruction-title");
  assert.deepEqual(
    titles.map((node) => node.textContent),
    ["Prefer impacted test selection"],
  );
  assert.equal(titles[0].href, "#/instructions");
  assert.deepEqual(
    byClass(panel, "workflow-instruction-reach").map(
      (node) => node.textContent,
    ),
    ["applies to 3 workflows / all projects"],
  );
});

test("a panel over a workflow nothing names says so instead of hiding", async () => {
  const documentNode = new FakeDocument();
  const client = instructionsClient({ instructions: [] });

  const panel = workflowInstructionsPanel(
    documentNode, { id: "dash" }, client,
  );
  await settle();

  assert.deepEqual(
    byClass(panel, "empty").map((node) => node.textContent),
    ["No active execution instructions apply to this workflow."],
  );
});
