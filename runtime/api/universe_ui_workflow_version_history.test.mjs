import assert from "node:assert/strict";
import test from "node:test";

import {
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  classText,
  mountWorkflows,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";
import {
  prototypeWorkflow,
} from "./universe_ui_workflow_prototype_test_support.mjs";

test("every version row explains its semantic delta from the previous version", async (t) => {
  const dash = prototypeWorkflow("dash");
  for (const version of dash.versions.slice(0, 2)) {
    const implementing = version.definition.stages.find(
      (stage) => stage.id === "implementing",
    );
    implementing.label = "work";
    implementing.gates = [];
    version.definition.entry_surfaces = version.definition.entry_surfaces
      .filter((surface) => surface !== "promotion");
  }
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient([dash]),
  );
  await settle();

  const deltas = classText(root, "workflow-version-delta");
  assert.equal(deltas.length, 3);
  assert.deepEqual(classText(root, "workflow-version-delta-label"), [
    "Since v2:",
  ]);
  assert.ok(classText(root, "workflow-version-delta-change").includes(
    "policy added: file budget = optional",
  ));
  assert.ok(classText(root, "workflow-version-delta-change").includes(
    'implementing: label "work" → "implementing"',
  ));
  assert.ok(classText(root, "workflow-version-delta-change").includes(
    "implementing: gate added: evidence_check",
  ));
  assert.ok(classText(root, "workflow-version-delta-change").includes(
    "entry surface added: promotion",
  ));
  assert.equal(deltas[1], "No surfaced changes since v1.");
  assert.equal(deltas[2], "First published version.");
  assert.equal(byClass(root, "workflow-version-when").length, 3);
  assert.equal(
    classText(root, "workflow-version-delta-change").some(
      (delta) => delta.includes("{"),
    ),
    false,
  );
  mounted.unmount();
});

test("Inspect renders the immutable version's own policy grid", async (t) => {
  const dash = prototypeWorkflow("dash");
  const { root, mounted } = await mountWorkflows(
    t, workflowsClient([dash]),
  );
  const rows = byClass(root, "workflow-version-row");
  const inspectV1 = allNodes(rows[2]).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Inspect",
  );
  inspectV1.dispatchEvent(new Event("click"));
  await settle();

  const labels = classText(root, "workflow-version-policy-label");
  const values = classText(root, "workflow-version-policy-value");
  assert.equal(labels.includes("File Budget"), true);
  assert.equal(
    values[labels.indexOf("File Budget")],
    "default (predates this version)",
  );
  assert.deepEqual(classText(root, "workflow-version-policy-heading"), [
    "Policies in v1",
  ]);
  mounted.unmount();
});
