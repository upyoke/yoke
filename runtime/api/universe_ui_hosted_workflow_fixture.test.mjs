import assert from "node:assert/strict";
import test from "node:test";

import {
  hostedFrameWorkflowClient,
} from "../../packages/yoke-core/src/yoke_core/ui/static/hosted_frame_workflows_fixture.js";

const EXPECTED_GATE_PLACEMENT = {
  dash: [
    [],
    ["work_claim_activation", "conflict_survey", "architecture_impact"],
    ["db_claim_prose", "db_mutation:evidence", "architecture_impact"],
    ["architecture_impact", "qa_verification", "dash_evidence"],
  ],
  blitz: [
    [],
    ["db_claim_prose", "db_mutation:joint"],
    ["db_claim_prose", "architecture_impact"],
    ["doc_claim_activation", "conflict_survey", "architecture_impact"],
    ["db_claim_prose", "db_mutation:evidence", "architecture_impact"],
    ["architecture_impact", "qa_verification", "doc_completion"],
  ],
  issue: [
    [],
    ["db_claim_prose", "db_mutation:joint"],
    ["db_claim_prose", "architecture_impact"],
    ["check_hard_blocks", "claim_activation", "architecture_impact"],
    ["db_claim_prose", "db_mutation:evidence", "architecture_impact"],
    ["architecture_impact", "path_claim_boundary", "qa_verification"],
    ["architecture_impact"],
    [
      "db_claim_prose",
      "db_mutation:polish",
      "architecture_impact",
      "path_claim_boundary",
      "qa_verification",
    ],
    ["architecture_impact", "path_claim_boundary", "qa_verification"],
    ["architecture_impact", "qa_verification"],
  ],
};

const EXPECTED_DESCRIPTION_COPY = {
  dash: {
    workflow:
      "A short instruction you file in seconds — filing is the spec; an agent executes it end-to-end.",
    implementing:
      "The agent surveys for conflicts, takes a worktree, and executes the instruction in one pass.",
    "reviewing-implementation":
      "The verification close — the agent self-checks, plus any case a tightened posture knob added.",
    done:
      "Result and verification evidence are recorded on the item; delivery, when enabled, ran as an after-merge action.",
  },
  blitz: {
    workflow:
      "Execute a strategy document directly; the item is only its coordination shell. Releases happen continuously inside implementing; the close reconciles the document.",
    implementing:
      "The continuous slice loop — the linked document is executed directly, and each slice may merge, migrate, and deploy; there is no separate release stage.",
    "reviewing-implementation":
      "The once-per-item close — the full suite runs and the document records what was completed, what changed, what remains, the evidence, and how the parent strategy was reconciled.",
    done:
      "The execution document states completion and parent reconciliation; that evidence is the entry gate.",
  },
  issue: {
    workflow:
      "One scoped implementation lane with planning, review, QA and delivery.",
    implementing:
      "One implementation lane in an isolated worktree; the engineer builds against the spec and acceptance criteria.",
    "reviewing-implementation":
      "The in-worktree review loop — the work is checked against the acceptance criteria before it can leave the lane.",
    done:
      "Merged and delivered through the selected flow; the item closes.",
  },
  epic: {
    workflow:
      "Planned task decomposition with parallel worktree lanes and an integration boundary.",
    planning:
      "The Architect decomposes the epic into tasks — file budgets, interface contracts, and worktree lanes.",
    "plan-drafted":
      "The task plan is drafted and awaits the refine pass before it can be committed.",
    "refining-plan":
      "The plan is refined against the spec — simplify lenses and readiness repair — before it commits.",
    planned:
      "The plan is committed and has passed the simulator; the tasks are ready to fan out into worktree lanes.",
    implementing:
      "Parallel task lanes execute against the plan, each in its own worktree, with the main session integrating.",
    "reviewing-implementation":
      "Integrated task work is reviewed across the whole epic before the set can advance.",
    done:
      "Every task merged, integrated, and delivered; the epic closes.",
  },
};

const EXPECTED_VERSION_ONE_DESCRIPTIONS = {
  dash: {
    implementing: "The skill surveys conflicts and completes the instruction.",
    "reviewing-implementation":
      "The skill self-checks plus any item-declared verification.",
    done: "The result and verification evidence are recorded on the item.",
  },
  blitz: {
    implementing:
      "The linked document drives a continuous loop of integrated slices.",
    "reviewing-implementation":
      "The complete result and its evidence are reconciled in the document.",
    done: "The document records completion and parent reconciliation.",
  },
  issue: {
    implementing:
      "One implementation lane builds against the item's acceptance criteria.",
    done: "The item is merged, delivered, and closed.",
  },
  epic: {
    planning: "The plan is decomposed into tasks, interfaces, budgets, and lanes.",
    planned: "The committed task plan has passed cross-task simulation.",
    implementing:
      "Task lanes execute in parallel and the main session integrates them.",
    done: "Every task is integrated, delivered, and closed.",
  },
};

const EXPECTED_GATE_COPY = {
  db_claim_prose:
    "The item's declared DB claim must agree with what its own text describes — prose about migrations alongside a claim of none is refused.",
  db_mutation:
    "A declared governed mutation must satisfy this point's check — joint: the strategy fits the project's breakage policy with no cross-item overlap; evidence: the authoritative apply evidence exists; polish: migration closeout is complete.",
  architecture_impact:
    "The item's declared architecture impact must honor the project's authoritative architecture model (the per-project architecture_model Project Structure family).",
  path_claim_boundary:
    "The item's changed files must stay inside its registered path claims.",
  plan_simulation:
    "The epic's plan must pass the simulator's cross-task execution trace.",
  qa_verification:
    "Every QA requirement materialized for this transition must be satisfied — passed or explicitly waived.",
  check_hard_blocks:
    "Every upstream item this one depends on must be finished before activation.",
  claim_activation:
    "Registered path claims activate together with the worktree; a conflicting live claim refuses activation.",
  work_claim_activation:
    "The executing session takes the exclusive work claim and a worktree.",
  doc_claim_activation:
    "The Blitz atomically claims its single execution document; an already-owned document refuses activation.",
  conflict_survey:
    "The agent reads claims, worktrees, and frontier items and aborts on any detected conflict.",
  doc_completion:
    "The strategy document must record what was completed, what changed, what remains, the evidence, and the parent reconciliation.",
  dash_evidence:
    "The result and verification evidence must be recorded on the item, plus every check the item's knobs declared — an attached plan passed, an approval resolved.",
};

EXPECTED_GATE_PLACEMENT.epic = [
  ...EXPECTED_GATE_PLACEMENT.issue.slice(0, 3),
  ["architecture_impact"],
  ["architecture_impact"],
  ["architecture_impact"],
  ["db_claim_prose", "architecture_impact", "plan_simulation"],
  ...EXPECTED_GATE_PLACEMENT.issue.slice(3),
];

function gateKey(gate) {
  return gate.mode ? `${gate.id}:${gate.mode}` : gate.id;
}

function historicalLabel(stageId) {
  const label = stageId.replaceAll("-", " ");
  return `${label.slice(0, 1).toUpperCase()}${label.slice(1)}`;
}

test("the hosted visual fixture preserves built-in gate placement", async () => {
  const response = await hostedFrameWorkflowClient().call({
    function: "workflows.definition.get",
    payload: {},
  });
  assert.equal(response.status, 200);

  for (const workflow of response.envelope.result.workflows) {
    assert.deepEqual(
      workflow.definition.stages.map(
        (stage) => stage.gates.map(gateKey),
      ),
      EXPECTED_GATE_PLACEMENT[workflow.id],
      workflow.id,
    );
  }
});

test("the hosted visual fixture serves the specification-owned copy", async () => {
  const response = await hostedFrameWorkflowClient().call({
    function: "workflows.definition.get",
    payload: {},
  });
  assert.equal(response.status, 200);

  for (const workflow of response.envelope.result.workflows) {
    assert.equal(workflow.current_version, 2, workflow.id);
    assert.deepEqual(
      workflow.versions.map((version) => version.version),
      [1, 2],
      workflow.id,
    );
    const expected = EXPECTED_DESCRIPTION_COPY[workflow.id];
    const { workflow: workflowDescription, ...stageDescriptions } = expected;
    assert.equal(workflow.description, workflowDescription, workflow.id);
    const descriptions = Object.fromEntries(
      workflow.definition.stages
        .filter((stage) => stage.description)
        .map((stage) => [stage.id, stage.description]),
    );
    assert.deepEqual(descriptions, stageDescriptions, workflow.id);
  }

  const catalog = Object.fromEntries(
    response.envelope.result.gate_catalog.map(
      (gate) => [gate.id, gate],
    ),
  );
  for (const [gateId, description] of Object.entries(EXPECTED_GATE_COPY)) {
    assert.equal(catalog[gateId].description, description, gateId);
    assert.equal(catalog[gateId].availability, "live", gateId);
  }
});

test("the hosted visual fixture serves distinct immutable version definitions", async () => {
  const client = hostedFrameWorkflowClient();
  for (const workflowId of ["dash", "blitz", "issue", "epic"]) {
    const historical = await client.call({
      function: "workflows.version.get",
      payload: { workflow_id: workflowId, version: 1 },
    });
    const current = await client.call({
      function: "workflows.version.get",
      payload: { workflow_id: workflowId, version: 2 },
    });
    const historicalDefinition = historical.envelope.result.definition;
    const currentDefinition = current.envelope.result.definition;

    assert.deepEqual(
      historicalDefinition.stages.map((stage) => stage.label),
      historicalDefinition.stages.map((stage) => historicalLabel(stage.id)),
      workflowId,
    );
    assert.deepEqual(
      Object.fromEntries(
        historicalDefinition.stages
          .filter((stage) => stage.description)
          .map((stage) => [stage.id, stage.description]),
      ),
      EXPECTED_VERSION_ONE_DESCRIPTIONS[workflowId],
      workflowId,
    );
    assert.equal(
      Object.hasOwn(historicalDefinition.policies, "approval_defaults"),
      false,
      workflowId,
    );
    assert.deepEqual(currentDefinition.policies.approval_defaults, {}, workflowId);
    if (["dash", "blitz"].includes(workflowId)) {
      assert.equal(
        Object.hasOwn(historicalDefinition.policies, "path_survey"),
        false,
        workflowId,
      );
      assert.equal(currentDefinition.policies.path_survey, "required", workflowId);
    }
    assert.notDeepEqual(historicalDefinition, currentDefinition, workflowId);
  }
});

test("the hosted visual fixture attributes locally published versions", async () => {
  const client = hostedFrameWorkflowClient();
  const published = await client.call({
    function: "workflows.policy_defaults.publish",
    payload: {
      workflow_id: "dash",
      expected_current_version: 2,
      path_claims_default: true,
    },
  });
  assert.equal(published.status, 200);

  const version = await client.call({
    function: "workflows.version.get",
    payload: { workflow_id: "dash", version: 3 },
  });
  assert.equal(version.envelope.result.published_by_actor_id, 1);
  assert.equal(
    version.envelope.result.definition.policies.path_claims,
    "required",
  );
});
