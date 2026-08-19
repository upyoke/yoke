import assert from "node:assert/strict";
import test from "node:test";

import {
  byClass,
} from "./universe_ui_dom_test_support.mjs";
import {
  classText,
  mountWorkflows,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";
import {
  enableTextNodes,
  prototypeWorkflow,
  selectWorkflow,
} from "./universe_ui_workflow_prototype_test_support.mjs";

const DELIVERY_COPY = {
  dash: "after done · closes on merge; delivery is separate",
  blitz: "during work · each slice proves delivery",
  issue: "before done · waits in release until delivered",
  epic: "before done · waits in release until delivered",
};

function deliveryCell(root) {
  return byClass(root, "workflow-posture-cell").find((cell) =>
    byClass(cell, "workflow-posture-name")[0]?.textContent === "Delivery");
}

test("delivery posture is locked and explains its timing", async (t) => {
  const workflows = ["dash", "blitz", "issue", "epic"]
    .map((id) => prototypeWorkflow(id));
  const { documentNode, root, mounted } = await mountWorkflows(
    t,
    workflowsClient(workflows),
  );

  for (const [id, expected] of Object.entries(DELIVERY_COPY)) {
    const name = `${id[0].toUpperCase()}${id.slice(1)}`;
    await selectWorkflow(documentNode, root, name);
    const cell = deliveryCell(root);
    assert.ok(cell, `${name} shows delivery posture`);
    assert.deepEqual(classText(cell, "workflow-posture-value"), [expected]);
    assert.deepEqual(classText(cell, "workflow-lock-pill"), [`🔒 ${name}`]);
    assert.equal(byClass(cell, "workflow-button").length, 0);
  }
  mounted.unmount();
});

test("a repeated gate reads as one re-asserted invariant", async (t) => {
  enableTextNodes(t);
  const issue = prototypeWorkflow("issue");
  const guardedStages = new Set([
    "implementing", "implemented", "release", "done",
  ]);
  for (const stage of issue.definition.stages) {
    stage.gates = guardedStages.has(stage.id)
      ? [{ id: "architecture_impact" }]
      : [];
  }
  const client = workflowsClient([issue]);
  const callBase = client.call.bind(client);
  client.call = async (request) => {
    const result = await callBase(request);
    if (request.function === "workflows.definition.get") {
      result.envelope.result.gate_catalog = [{
        id: "architecture_impact",
        name: "Architecture impact",
        description: "Honor the architecture_model family.",
      }];
    }
    return result;
  };
  const { root, mounted } = await mountWorkflows(t, client);

  assert.equal(
    classText(root, "workflow-stage-count")
      .filter((value) => value === "1 check").length,
    4,
  );
  for (const stageId of ["implementing", "done"]) {
    byClass(root, "workflow-stage").find(
      (node) =>
        byClass(node, "workflow-stage-label")[0]?.textContent === stageId,
    ).dispatchEvent(new Event("click"));
    assert.deepEqual(
      classText(root, "workflow-gate-reassertion"),
      ["Re-asserted invariant."],
    );
    const description = byClass(
      root, "workflow-detail-row-description",
    )[0].children.map((node) => node.textContent).join("");
    assert.match(
      description,
      /same rule is re-checked on entry to implementing, implemented, release, and done/i,
    );
  }
  mounted.unmount();
});
