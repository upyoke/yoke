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
  workflowFixture,
  workflowsClient,
} from "./universe_ui_workflows_test_support.mjs";
import {
  workflowInstructionsPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/workflow_instructions_panel.js";

const LONG_BODY = "First line of the instruction.\nSecond line stays visible only after expand.";

function instructionsClient(seed = []) {
  return {
    async call(request) {
      if (request.function === "workflow.execution_instruction.list") {
        return okEnvelope({ instructions: seed.map((row) => ({ ...row })) });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountPanel(seed, extra = {}) {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  host.appendChild(workflowInstructionsPanel(
    documentNode,
    extra.client || instructionsClient(seed),
    {
      workflows: extra.workflows || [
        { id: "dash", name: "Dash" },
        { id: "issue", name: "Issue" },
      ],
      projects: extra.projects || [{ id: 1, slug: "yoke" }, { id: 2, slug: "platform" }],
    },
  ));
  await settle();
  return { documentNode, host };
}

function buttonByText(host, text) {
  return allNodes(host).find(
    (node) => node.tagName === "BUTTON" && node.textContent === text,
  );
}

async function settleUntil(predicate) {
  for (let attempt = 0; attempt < 16; attempt += 1) {
    await settle();
    if (predicate()) return;
  }
}

test("Show more reveals the full body in place and Show less restores the preview", async () => {
  const { host } = await mountPanel([{
    id: 11,
    content: LONG_BODY,
    applies_to_all_workflows: true,
    applies_to_all_projects: true,
  }]);

  assert.deepEqual(classText(host, "workflow-instruction-content"), [
    "First line of the instruction.",
  ]);
  assert.equal(byClass(host, "workflow-instruction-body").length, 0);
  const expand = byClass(host, "workflow-instruction-expand")[0];
  assert.equal(expand.textContent, "Show more");
  assert.equal(expand.attributes.get("aria-expanded"), "false");
  assert.equal(expand.attributes.get("aria-controls"), "instruction-body-11");

  expand.dispatchEvent(new Event("click"));
  const body = byClass(host, "workflow-instruction-body")[0];
  assert.equal(body.textContent, LONG_BODY);
  assert.equal(byClass(host, "workflow-instruction-content").length, 0);
  const collapse = byClass(host, "workflow-instruction-expand")[0];
  assert.equal(collapse.textContent, "Show less");
  assert.equal(collapse.attributes.get("aria-expanded"), "true");

  collapse.dispatchEvent(new Event("click"));
  assert.deepEqual(classText(host, "workflow-instruction-content"), [
    "First line of the instruction.",
  ]);
});

test("explicit filters hide rows without the selected tab changing ownership", async () => {
  const { host } = await mountPanel([
    {
      id: 1,
      content: "Everyone",
      applies_to_all_workflows: true,
      applies_to_all_projects: true,
    },
    { id: 2, content: "Dash only", workflow_ids: ["dash"], project_ids: [1] },
    { id: 3, content: "Issue only", workflow_ids: ["issue"], project_ids: [] },
  ]);

  assert.deepEqual(classText(host, "workflow-instruction-content"), [
    "Everyone", "Dash only", "Issue only",
  ]);
  const workflowFilter = byClass(host, "workflow-instruction-workflow-filter")[0];
  workflowFilter.value = "dash";
  workflowFilter.dispatchEvent(new Event("change"));
  assert.deepEqual(classText(host, "workflow-instruction-content"), [
    "Everyone", "Dash only",
  ]);
  workflowFilter.value = "";
  workflowFilter.dispatchEvent(new Event("change"));
  const projectFilter = byClass(host, "workflow-instruction-project-filter")[0];
  projectFilter.value = "1";
  projectFilter.dispatchEvent(new Event("change"));
  assert.deepEqual(classText(host, "workflow-instruction-content"), [
    "Everyone", "Dash only",
  ]);
});

test("expanded body survives switching the workflow tab", async (t) => {
  const client = workflowsClient([
    workflowFixture({ id: "dash", name: "Dash" }),
    workflowFixture({ id: "issue", name: "Issue" }),
  ]);
  const inner = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "workflow.execution_instruction.list") {
      client.requests.push(request);
      return okEnvelope({
        instructions: [{
          id: 11,
          content: LONG_BODY,
          applies_to_all_workflows: true,
          applies_to_all_projects: true,
        }],
      });
    }
    return inner(request);
  };
  const { documentNode, root, mounted } = await mountWorkflows(t, client);
  documentNode.defaultView.history = {
    state: null,
    replaceState(state) { this.state = state; },
  };
  await settleUntil(() => byClass(root, "workflow-instruction-expand").length);
  const expand = byClass(root, "workflow-instruction-expand")[0];
  expand.dispatchEvent(new Event("click"));
  assert.equal(byClass(root, "workflow-instruction-body")[0].textContent, LONG_BODY);
  const issueTab = byClass(root, "workflow-tab").find(
    (node) => node.textContent === "Issue",
  );
  assert.ok(issueTab, "Issue tab exists");
  issueTab.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(byClass(root, "workflow-instruction-body")[0].textContent, LONG_BODY);
  assert.equal(
    byClass(root, "workflow-instruction-expand")[0].textContent,
    "Show less",
  );
  assert.equal(
    byClass(root, "workflow-tab").find((node) => node.textContent === "Issue")
      .attributes.get("aria-selected"),
    "true",
  );
  mounted.unmount();
});

test("list errors and loading stay visible on the instructions panel", async () => {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  const pending = workflowInstructionsPanel(documentNode, {
    async call() {
      return new Promise(() => {});
    },
  }, { workflows: [], projects: [] });
  host.appendChild(pending);
  assert.equal(byClass(host, "panel-body")[0].textContent, "loading…");

  const { host: failed } = await mountPanel([], {
    client: {
      async call() {
        return {
          status: 500,
          envelope: { success: false, error: { message: "list failed" } },
        };
      },
    },
    workflows: [],
    projects: [],
  });
  assert.match(failed.textContent, /list failed/);
});
