import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  classText,
  mountWorkflows,
  panelTitles,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";

import {
  cssRule,
  DESCRIPTIONS,
  enableTextNodes,
  prototypeWorkflow,
  selectWorkflow,
  STAGES,
} from "./universe_ui_workflow_prototype_test_support.mjs";

test("the four workflow tabs and lifecycle shapes follow the prototype", async (t) => {
  const workflows = [
    prototypeWorkflow("epic"),
    prototypeWorkflow("issue"),
    prototypeWorkflow("dash"),
    prototypeWorkflow("blitz"),
  ];
  const { documentNode, root, mounted } = await mountWorkflows(
    t, workflowsClient(workflows),
  );

  assert.deepEqual(classText(root, "workflow-tab"), [
    "Dash", "Blitz", "Issue", "Epic",
  ]);
  assert.deepEqual(
    byClass(root, "workflow-tab").map(
      (node) => node.attributes.get("role"),
    ),
    ["tab", "tab", "tab", "tab"],
  );
  for (const id of ["dash", "blitz", "issue", "epic"]) {
    const name = `${id[0].toUpperCase()}${id.slice(1)}`;
    await selectWorkflow(documentNode, root, name);
    assert.deepEqual(classText(root, "workflow-intro"), [DESCRIPTIONS[id]]);
    assert.deepEqual(classText(root, "workflow-stage-label"), STAGES[id]);
    assert.deepEqual(
      panelTitles(root),
      [
        "Stages", "Execution posture", "Mechanics",
        "Execution instructions", "Version history",
      ],
    );
  }
  mounted.unmount();
});

test("workflow posture follows the selected immutable version", async (t) => {
  const historical = prototypeWorkflow("dash");
  historical.current_version = 2;
  historical.definition = structuredClone(historical.versions[1].definition);
  const oldView = await mountWorkflows(
    t, workflowsClient([historical]),
  );
  assert.equal(
    byClass(oldView.root, "workflow-posture-label").some(
      (node) => node.children.at(-1)?.textContent === "File Budget",
    ),
    false,
  );
  oldView.mounted.unmount();

  const currentView = await mountWorkflows(
    t, workflowsClient([prototypeWorkflow("dash")]),
  );
  assert.equal(
    byClass(currentView.root, "workflow-posture-label").some(
      (node) => node.children.at(-1)?.textContent === "File Budget",
    ),
    true,
  );
  currentView.mounted.unmount();
});

test("workflow tabs switch immediately and remember each selected stage", async (t) => {
  const client = workflowsClient([
    prototypeWorkflow("dash"),
    prototypeWorkflow("blitz"),
  ]);
  const { documentNode, root, mounted } = await mountWorkflows(t, client);
  const replacedRoutes = [];
  documentNode.defaultView.history = {
    state: null,
    replaceState(state, _title, route) {
      this.state = state;
      documentNode.defaultView.location.hash = route;
      replacedRoutes.push(route);
    },
  };

  byClass(root, "workflow-stage")[1].dispatchEvent(new Event("click"));
  byClass(root, "workflow-tab").find(
    (node) => node.textContent === "Blitz",
  ).dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-stage-detail-label"), ["idea"]);
  byClass(root, "workflow-stage")[3].dispatchEvent(new Event("click"));

  byClass(root, "workflow-tab").find(
    (node) => node.textContent === "Dash",
  ).dispatchEvent(new Event("click"));
  assert.deepEqual(
    classText(root, "workflow-stage-detail-label"),
    ["implementing"],
  );
  byClass(root, "workflow-tab").find(
    (node) => node.textContent === "Blitz",
  ).dispatchEvent(new Event("click"));
  assert.deepEqual(
    classText(root, "workflow-stage-detail-label"),
    ["implementing"],
  );
  assert.deepEqual(replacedRoutes, [
    "#/workflows/blitz",
    "#/workflows/dash",
    "#/workflows/blitz",
  ]);
  assert.equal(
    client.requests.filter(
      (request) => request.function === "workflows.definition.get",
    ).length,
    1,
  );
  mounted.unmount();
});

test("workflow inline typography preserves prototype emphasis", async (t) => {
  enableTextNodes(t);
  const dash = prototypeWorkflow("dash");
  dash.definition.stages[1].gates = [{ id: "architecture_impact" }];
  const client = workflowsClient([dash]);
  const callBase = client.call.bind(client);
  client.call = async (request) => {
    const result = await callBase(request);
    if (request.function === "workflows.definition.get") {
      result.envelope.result.gate_catalog = [{
        id: "architecture_impact",
        name: "Architecture impact",
        description:
          "Honor the per-project architecture_model Project Structure family.",
      }];
    }
    return result;
  };
  const { root, mounted } = await mountWorkflows(t, client);

  assert.ok(classText(root, "workflow-inline-code").includes("/yoke curate"));
  assert.ok(classText(root, "workflow-inline-code").includes("/yoke dash"));
  byClass(root, "workflow-stage")[1].dispatchEvent(new Event("click"));
  assert.ok(
    classText(root, "workflow-inline-code").includes("architecture_model"),
  );

  allNodes(root).find(
    (node) => node.tagName === "BUTTON" &&
      node.textContent === "Set universe defaults for Dash",
  ).dispatchEvent(new Event("click"));
  assert.ok(
    classText(root, "workflow-inline-strong").includes("implementing"),
  );
  byClass(root, "workflow-checkbox")[0].children[0]
    .dispatchEvent(new Event("change"));
  assert.deepEqual(
    classText(root, "workflow-configured-stage"),
    ["implementing"],
  );
  mounted.unmount();
});

test("workflow desktop styles retain the prototype header and timeline rhythm", () => {
  const workflowsCss = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/workflows.css",
    import.meta.url,
  ), "utf8");
  const controlsCss = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/workflow_controls.css",
    import.meta.url,
  ), "utf8");

  assert.match(
    cssRule(
      workflowsCss,
      ".universe-app-root .workflow-panel-meta",
    ),
    /font-size: 12px;/,
  );
  assert.match(
    cssRule(workflowsCss, ".universe-app-root .workflow-version"),
    /font-weight: 600;/,
  );
  assert.match(
    cssRule(
      workflowsCss,
      ".universe-app-root .workflow-panel-header .panel-count",
    ),
    /margin-left: 10px;/,
  );
  assert.match(
    controlsCss,
    /\.universe-app-root \.workflow-version-row:last-child \{/,
  );
  assert.doesNotMatch(
    controlsCss,
    /\.workflow-version-row:last-of-type/,
  );
  assert.doesNotMatch(
    cssRule(workflowsCss, ".universe-app-root .workflow-tab"),
    /margin-bottom:/,
  );
  assert.doesNotMatch(workflowsCss, /\.workflow-stage:hover/);
  assert.doesNotMatch(
    workflowsCss,
    /\.workflow-(?:home|entry)-link[\s\S]*?:hover/,
  );
  assert.match(
    cssRule(
      controlsCss,
      ".universe-app-root .workflow-dialog-subtitle",
    ),
    /margin: 0 0 14px;/,
  );
  assert.match(
    workflowsCss,
    /\.workflow-inline-code,[\s\S]*?background: transparent;/,
  );
  const noChecks = cssRule(
    workflowsCss, ".universe-app-root .workflow-no-checks",
  );
  assert.match(noChecks, /margin: 0;/);
  assert.match(noChecks, /font-style: normal;/);
});

test("workflow mechanics keep project-owned defaults separate from definitions", async (t) => {
  const workflows = ["epic", "issue", "blitz", "dash"].map(prototypeWorkflow);
  const expected = {
    Dash: [
      "Default test plan — set per project.",
      "Default deployment flow — set per project.",
    ],
    Blitz: [
      "Default test plan — set per project.",
      "Default deployment flow — set per project.",
    ],
    Issue: [
      "Default test plan — set per project.",
      "Default deployment flow — set per project.",
    ],
    Epic: [
      "Default test plan — set per project.",
      "Default deployment flow — set per project.",
    ],
  };
  const { documentNode, root, mounted } = await mountWorkflows(
    t, workflowsClient(workflows),
  );

  for (const [name, copy] of Object.entries(expected)) {
    await selectWorkflow(documentNode, root, name);
    const descriptions = classText(root, "workflow-detail-row-description");
    for (const line of copy) assert.ok(descriptions.includes(line));
  }
  mounted.unmount();
});

test("a non-entry stage with no gate explains that nothing is checked", async (t) => {
  const workflow = prototypeWorkflow("dash");
  workflow.definition.stages[1] = {
    id: "implementing",
    label: "implementing",
    gates: [],
    description: "The agent executes the instruction in one pass.",
  };
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient([workflow]),
  );

  byClass(root, "workflow-stage")[1].dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-stage-detail-count"), [
    "• no checks on entry",
  ]);
  assert.deepEqual(classText(root, "workflow-no-checks"), [
    "Nothing is checked on entry.",
  ]);
  mounted.unmount();
});

test("empty registry and empty version history keep explicit product states", async (t) => {
  const empty = await mountWorkflows(t, workflowsClient([]));
  assert.deepEqual(classText(empty.root, "empty"), [
    "No workflows declared.",
  ]);
  empty.mounted.unmount();

  const noVersions = prototypeWorkflow("dash");
  noVersions.versions = [];
  const mounted = await mountWorkflows(
    t, workflowsClient([noVersions]),
  );
  assert.deepEqual(classText(mounted.root, "empty"), [
    "No active execution instructions apply to this workflow.",
    "No published versions.",
  ]);
  mounted.mounted.unmount();
});

test("a rejected secondary mechanics read leaves the registry readable", async (t) => {
  const client = workflowsClient([prototypeWorkflow("dash")]);
  const baseCall = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflows.mechanics.get") {
      client.requests.push(request);
      throw new Error("mechanics transport unavailable");
    }
    return baseCall(request);
  };
  const { root, mounted } = await mountWorkflows(t, client);

  assert.deepEqual(classText(root, "workflow-tab"), ["Dash"]);
  assert.deepEqual(
    panelTitles(root),
    [
      "Stages", "Execution posture", "Mechanics",
      "Execution instructions", "Version history",
    ],
  );
  assert.equal(
    allNodes(root).some(
      (node) => node.tagName === "BUTTON" &&
        node.textContent.startsWith("Edit Dash defaults"),
    ),
    false,
  );
  mounted.unmount();
});
