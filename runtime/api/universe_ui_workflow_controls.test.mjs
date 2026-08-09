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
  okEnvelope,
  workflowFixture,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";

test("workflow tabs use the decided built-in order and open Dash first", async (t) => {
  const workflows = [
    workflowFixture({ id: "epic", name: "Epic", currentVersion: 1 }),
    workflowFixture({ id: "issue", name: "Issue", currentVersion: 1 }),
    workflowFixture({ id: "blitz", name: "Blitz", currentVersion: 1 }),
    workflowFixture({
      id: "dash",
      name: "Dash",
      description:
        "A short instruction you file in seconds — filing is the spec; " +
        "an agent executes it end-to-end.",
      currentVersion: 1,
    }),
    workflowFixture({ id: "rally", name: "Rally", currentVersion: 1 }),
  ];
  const { documentNode, root, mounted } = await mountWorkflows(
    t, workflowsClient(workflows),
  );

  assert.deepEqual(classText(root, "workflow-tab"), [
    "Dash", "Blitz", "Issue", "Epic", "Rally",
  ]);
  assert.equal(
    byClass(root, "workflow-tab")[0].attributes.get("aria-selected"),
    "true",
  );
  assert.deepEqual(classText(root, "workflow-intro"), [
    "A short instruction you file in seconds — filing is the spec; " +
      "an agent executes it end-to-end.",
  ]);

  byClass(root, "workflow-tab")[2].dispatchEvent(new Event("click"));
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();
  assert.equal(
    documentNode.defaultView.location.hash,
    "#/workflows/issue",
  );
  assert.equal(
    byClass(root, "workflow-tab")[2].attributes.get("aria-selected"),
    "true",
  );
  assert.deepEqual(classText(root, "workflow-intro"), [
    "Coordinate a small release train.",
  ]);
  mounted.unmount();
});

test("a workflow detail route selects the linked definition", async (t) => {
  const workflows = [
    workflowFixture({ id: "dash", name: "Dash", currentVersion: 1 }),
    workflowFixture({ id: "epic", name: "Epic", currentVersion: 1 }),
  ];
  const { root, mounted } = await mountWorkflows(
    t,
    workflowsClient(workflows),
    "#/workflows/epic",
  );

  assert.deepEqual(classText(root, "workflow-tab"), ["Dash", "Epic"]);
  assert.equal(
    byClass(root, "workflow-tab")[1].attributes.get("aria-selected"),
    "true",
  );
  assert.deepEqual(classText(root, "workflow-intro"), [
    "Coordinate a small release train.",
  ]);
  mounted.unmount();
});

test("version inspection reads the immutable definition and can select it", async (t) => {
  const rally = workflowFixture();
  const historicalDefinition = structuredClone(rally.definition);
  historicalDefinition.stages[0].label = "Filed";
  rally.versions[0].definition = historicalDefinition;
  const client = workflowsClient([rally]);
  const { root, mounted } = await mountWorkflows(t, client);
  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Inspect",
  ).dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(classText(root, "workflow-version-digest"), [
    "rally-first",
  ]);
  assert.deepEqual(classText(root, "workflow-version-stages"), [
    "Filed → Proving → Shipped",
  ]);
  assert.ok(allNodes(root).some(
    (node) => node.tagName === "BUTTON" &&
      node.textContent === "Hide" &&
      node.attributes.get("aria-expanded") === "true",
  ));
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.version.get",
    ),
    {
      function: "workflows.version.get",
      payload: { workflow_id: "rally", version: 1 },
    },
  );

  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Make current",
  ).dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Make Rally v1 current?",
  ]);
  byClass(root, "primary")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.current.set",
    ),
    {
      function: "workflows.current.set",
      payload: {
        workflow_id: "rally",
        version: 1,
        expected_current_version: 3,
      },
    },
  );
  assert.deepEqual(classText(root, "workflow-version-title"), [
    "v3", "v1 · current",
  ]);
  assert.deepEqual(classText(root, "workflow-stage-label"), [
    "Filed", "Proving", "Shipped",
  ]);
  mounted.unmount();
});

test("version inspection exposes stable loading, retry, and collapse states", async (t) => {
  const client = workflowsClient();
  const callBase = client.call.bind(client);
  let attempts = 0;
  client.call = async (request) => {
    if (request.function === "workflows.version.get") {
      attempts += 1;
      if (attempts === 1) {
        client.requests.push(request);
        throw new Error("version read unavailable");
      }
    }
    return callBase(request);
  };
  const { root, mounted } = await mountWorkflows(t, client);

  const inspect = allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Inspect",
  );
  inspect.dispatchEvent(new Event("click"));
  assert.equal(inspect.disabled, true);
  assert.equal(inspect.textContent, "Inspecting…");
  assert.equal(inspect.attributes.get("aria-expanded"), "true");
  await settle();

  assert.equal(inspect.disabled, false);
  assert.equal(inspect.textContent, "Retry");
  assert.ok(classText(root, "workflow-version-inspection")[0].includes(
    "version read unavailable",
  ));
  inspect.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(inspect.textContent, "Hide");
  assert.deepEqual(classText(root, "workflow-version-digest"), [
    "rally-first",
  ]);

  inspect.dispatchEvent(new Event("click"));
  assert.equal(inspect.textContent, "Inspect");
  assert.equal(inspect.attributes.get("aria-expanded"), "false");
  assert.equal(byClass(root, "workflow-version-inspection").length, 0);
  mounted.unmount();
});

test("the editable path-claims default publishes a new immutable version", async (t) => {
  const dash = workflowFixture({
    id: "dash",
    name: "Dash",
    currentVersion: 1,
    skillBindings: [{
      skill_id: "dash",
      from_stage_id: "draft",
      through_stage_id: "ship",
    }],
    policies: {
      ownership: "exclusive_session_work_claim",
      file_budget: "optional",
      path_claims: "optional",
      worktrees: "single_implementation_lane",
      generated_children: "none",
      qa: "optional_item_attachment",
      approvals: "none",
      delivery: "after_merge_action",
      item_posture_allowlist: [
        "verification", "path_claims", "approval_on_done", "deployment",
      ],
    },
  });
  const client = workflowsClient([dash]);
  const { root, mounted } = await mountWorkflows(t, client);

  const turnOn = allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Turn on",
  );
  assert.ok(turnOn);
  turnOn.dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Turn on path claims",
  ]);
  assert.equal(
    byClass(root, "workflow-dialog")[0].attributes.get("aria-label"),
    "Turn on path claims",
  );
  assert.ok(classText(root, "workflow-dialog-impact")[0].includes(
    "Editing creates a new version of the Dash workflow in your Yoke universe",
  ));
  byClass(root, "primary")[0].dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.policy_defaults.publish",
    ),
    {
      function: "workflows.policy_defaults.publish",
      payload: {
        workflow_id: "dash",
        expected_current_version: 1,
        path_claims_default: true,
      },
    },
  );
  assert.ok(classText(root, "workflow-posture-value").includes("on by default"));
  assert.ok(classText(root, "workflow-posture-value").includes("one"));
  assert.ok(classText(root, "workflow-detail-row-description").includes(
    "Run /yoke dash in a supported harness like Claude Code or Codex — " +
    "it runs the whole item: survey, worktree, execute, verify, merge, evidence.",
  ));
  assert.deepEqual(classText(root, "workflow-version-title"), [
    "v2 · current", "v1",
  ]);
  assert.equal(
    classText(root, "workflow-version-description")[0],
    "edited here",
  );
  const publishedVersion = await client.call({
    function: "workflows.version.get",
    payload: { workflow_id: "dash", version: 2 },
  });
  assert.equal(publishedVersion.envelope.result.published_by_actor_id, 1);
  mounted.unmount();
});

test("a failed path-claims publish restores its dialog controls", async (t) => {
  const dash = workflowFixture({
    id: "dash",
    name: "Dash",
    currentVersion: 1,
    policies: {
      ownership: "exclusive_session_work_claim",
      file_budget: "optional",
      path_claims: "optional",
      worktrees: "single_implementation_lane",
      generated_children: "none",
      qa: "optional_item_attachment",
      approvals: "none",
      delivery: "after_merge_action",
      item_posture_allowlist: ["path_claims"],
    },
  });
  const client = workflowsClient([dash]);
  const callBase = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflows.policy_defaults.publish") {
      throw new Error("publish unavailable");
    }
    return callBase(request);
  };
  const { root, mounted } = await mountWorkflows(t, client);

  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Turn on",
  ).dispatchEvent(new Event("click"));
  const confirm = byClass(root, "primary")[0];
  const cancel = allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Cancel",
  );
  confirm.dispatchEvent(new Event("click"));
  assert.equal(confirm.textContent, "Saving…");
  await settle();

  assert.equal(confirm.textContent, "Turn on path claims");
  assert.equal(confirm.disabled, false);
  assert.equal(cancel.disabled, false);
  assert.deepEqual(classText(root, "workflow-dialog-error"), [
    "publish unavailable",
  ]);
  assert.equal(byClass(root, "workflow-dialog-error")[0].hidden, false);
  mounted.unmount();
});

test("a failed registry read renders one honest screen failure", async (t) => {
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      return {
        status: 500,
        envelope: {
          success: false,
          error: { message: "definition read broke" },
        },
      };
    },
  };
  const { root, mounted } = await mountWorkflows(t, client);
  const errors = byClass(root, "error");
  assert.equal(errors.length, 1);
  assert.ok(errors[0].textContent.includes("definition read broke"));
  mounted.unmount();
});
