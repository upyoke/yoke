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
  okEnvelope,
  panelTitles,
  workflowFixture,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";

function dashFixture() {
  return workflowFixture({
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
      approval_defaults: {},
      delivery: "after_merge_action",
      item_posture_allowlist: [
        "verification", "file_budget", "path_claims",
        "approval_on_done", "deployment",
      ],
    },
  });
}

function mechanicsClient() {
  const base = workflowsClient([dashFixture()]);
  const callBase = base.call.bind(base);
  base.call = async (request) => {
    if (request.function === "workflows.definition.get") {
      const result = await callBase(request);
      result.envelope.result.flows = [{
        id: "yoke-production",
        name: "Yoke production",
        project: "yoke",
        status: "active",
      }];
      return result;
    }
    if (request.function === "workflows.mechanics.get") {
      base.requests.push(request);
      return okEnvelope({
        testing_defaults: [],
        delivery_defaults: [],
        approvers: [{ id: 2, label: "ben" }],
      });
    }
    if (request.function === "qa.plan.list") {
      base.requests.push(request);
      return okEnvelope({
        rows: [{
          id: 9,
          project: "yoke",
          slug: "release-readiness",
          name: "Release readiness",
          attachments: [],
        }],
      });
    }
    if (
      request.function === "workflows.testing_default.set" ||
      request.function === "workflows.delivery_default.set" ||
      request.function === "workflows.approval_defaults.publish"
    ) {
      base.requests.push(request);
      return okEnvelope({ result: { changed: true } });
    }
    return callBase(request);
  };
  return base;
}

function buttonByText(root, text) {
  return allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === text,
  );
}

function cssRule(source, selector) {
  const marker = `${selector} {`;
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, `${selector} exists`);
  return source.slice(start, source.indexOf("}", start) + 1);
}

test("approval editor publishes structured addressees as a new version", async (t) => {
  const client = mechanicsClient();
  const { root, mounted } = await mountWorkflows(t, client);

  buttonByText(root, "Set universe defaults for Dash")
    .dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Default approvals — Dash",
  ]);
  assert.equal(
    byClass(root, "workflow-dialog")[0].attributes.get("aria-label"),
    "Default approvals — Dash",
  );
  const transition = allNodes(root).find(
    (node) => node.tagName === "SELECT",
  );
  assert.deepEqual(
    Array.from(transition.children).map((node) => node.textContent),
    ["prove", "ship"],
  );
  assert.deepEqual(classText(root, "workflow-field-help").slice(0, 1), [
    "Anyone who matches may approve prove",
  ]);
  assert.equal(byClass(root, "workflow-checkbox").length, 4);
  byClass(root, "workflow-checkbox")[0].children[0]
    .dispatchEvent(new Event("change"));
  assert.deepEqual(classText(root, "workflow-configured-summary"), [
    "Gates set: prove",
  ]);
  buttonByText(root, "Save universe default")
    .dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.approval_defaults.publish",
    ),
    {
      function: "workflows.approval_defaults.publish",
      payload: {
        workflow_id: "dash",
        expected_current_version: 1,
        approval_defaults: {
          prove: { roles: ["owner"], actors: [] },
        },
      },
    },
  );
  mounted.unmount();
});

test("a failed mechanics save restores the editor controls", async (t) => {
  const client = mechanicsClient();
  const callBase = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflows.approval_defaults.publish") {
      throw new Error("approval save unavailable");
    }
    return callBase(request);
  };
  const { root, mounted } = await mountWorkflows(t, client);

  buttonByText(root, "Set universe defaults for Dash")
    .dispatchEvent(new Event("click"));
  const confirm = buttonByText(root, "Save universe default");
  const cancel = buttonByText(root, "Cancel");
  confirm.dispatchEvent(new Event("click"));
  assert.equal(confirm.textContent, "Saving…");
  await settle();

  assert.equal(confirm.textContent, "Save universe default");
  assert.equal(confirm.disabled, false);
  assert.equal(cancel.disabled, false);
  assert.deepEqual(classText(root, "workflow-dialog-error"), [
    "approval save unavailable",
  ]);
  assert.equal(byClass(root, "workflow-dialog-error")[0].hidden, false);
  mounted.unmount();
});

test("mechanics dialogs trap focus, close on Escape, and restore the opener", async (t) => {
  const client = mechanicsClient();
  const { documentNode, root, mounted } = await mountWorkflows(t, client);
  const trigger = buttonByText(root, "Set universe defaults for Dash");
  trigger.focus();
  trigger.dispatchEvent(new Event("click"));

  const cancel = buttonByText(root, "Cancel");
  const confirm = buttonByText(root, "Save universe default");
  assert.equal(documentNode.activeElement, cancel);

  const forward = new Event("keydown");
  Object.defineProperty(forward, "key", { value: "Tab" });
  documentNode.defaultView.dispatchEvent(forward);
  assert.equal(documentNode.activeElement, confirm);

  const wrap = new Event("keydown");
  Object.defineProperty(wrap, "key", { value: "Tab" });
  documentNode.defaultView.dispatchEvent(wrap);
  assert.equal(documentNode.activeElement.tagName, "SELECT");

  const backward = new Event("keydown");
  Object.defineProperties(backward, {
    key: { value: "Tab" },
    shiftKey: { value: true },
  });
  documentNode.defaultView.dispatchEvent(backward);
  assert.equal(documentNode.activeElement, confirm);

  const escape = new Event("keydown");
  Object.defineProperty(escape, "key", { value: "Escape" });
  documentNode.defaultView.dispatchEvent(escape);
  assert.equal(byClass(root, "workflow-dialog").length, 0);
  assert.equal(documentNode.activeElement, trigger);
  mounted.unmount();
});

test("Testing and Delivery editors stay project-owned and can apply broadly", async (t) => {
  const client = mechanicsClient();
  const { root, mounted } = await mountWorkflows(t, client);

  buttonByText(root, "Edit Dash defaults for each project")
    .dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Default test plan — Dash",
  ]);
  assert.equal(
    byClass(root, "workflow-dialog-footer")[0]
      .classList.contains("actions-only"),
    true,
  );
  byClass(root, "workflow-checkbox")[0].children[0]
    .dispatchEvent(new Event("change"));
  buttonByText(root, "Set default").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.testing_default.set",
    ),
    {
      function: "workflows.testing_default.set",
      payload: {
        project: "yoke",
        workflow_id: "dash",
        plan_id: 9,
        apply_to_all: true,
      },
    },
  );

  const deliveryButtons = allNodes(root).filter(
    (node) => node.tagName === "BUTTON" &&
      node.textContent === "Edit Dash defaults for each project",
  );
  deliveryButtons[1].dispatchEvent(new Event("click"));
  assert.deepEqual(classText(root, "workflow-dialog-title"), [
    "Default deployment flow — Dash",
  ]);
  assert.equal(
    byClass(root, "workflow-dialog-footer")[0]
      .classList.contains("actions-only"),
    true,
  );
  buttonByText(root, "Set default").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "workflows.delivery_default.set",
    ),
    {
      function: "workflows.delivery_default.set",
      payload: {
        project: "yoke",
        workflow_id: "dash",
        flow_id: "yoke-production",
        apply_to_all: false,
      },
    },
  );
  mounted.unmount();
});

test("mechanics dialogs preserve the prototype desktop control treatment", () => {
  const mechanicsCss = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/workflow_mechanics.css",
    import.meta.url,
  ), "utf8");
  const controlsCss = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/workflow_controls.css",
    import.meta.url,
  ), "utf8");
  const field = cssRule(
    mechanicsCss, ".universe-app-root .workflow-field",
  );
  assert.match(field, /width: 100%;/);
  assert.match(field, /margin-bottom: 12px;/);
  assert.doesNotMatch(
    field,
    /min-height|padding|border|background|font|color/,
  );
  assert.match(
    cssRule(
      mechanicsCss,
      ".universe-app-root .workflow-checkbox",
    ),
    /color: var\(--yoke-ink\);/,
  );
  assert.doesNotMatch(mechanicsCss, /accent-color:/);
  assert.match(
    cssRule(
      controlsCss,
      ".universe-app-root .workflow-dialog-footer.actions-only",
    ),
    /justify-content: flex-end;/,
  );
});

test("registry policy controls do not depend on the mechanics read", async (t) => {
  const client = workflowsClient([dashFixture()]);
  const callBase = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflows.mechanics.get") {
      client.requests.push(request);
      return {
        status: 200,
        envelope: {
          success: false,
          error: { message: "org admin required" },
        },
      };
    }
    return callBase(request);
  };
  const { root, mounted } = await mountWorkflows(t, client);

  assert.deepEqual(classText(root, "workflow-tab"), ["Dash"]);
  assert.ok(panelTitles(root).includes("Stages"));
  assert.equal(
    buttonByText(root, "Set universe defaults for Dash"),
    undefined,
  );
  assert.equal(
    buttonByText(root, "Edit Dash defaults for each project"),
    undefined,
  );
  assert.ok(buttonByText(root, "Turn on"));
  mounted.unmount();
});
