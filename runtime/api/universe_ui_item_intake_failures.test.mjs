import assert from "node:assert/strict";
import test from "node:test";

import {
  renderNewItemView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_new.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";

function dashWorkflow(allow = []) {
  return {
    id: "dash",
    name: "Dash",
    definition: {
      entry_surfaces: ["web_form"],
      policies: { item_posture_allowlist: allow },
    },
  };
}

function intakeClient({
  workflows = [dashWorkflow()],
  plans = [],
  methods = [],
  definitionFailure = null,
  planFailure = null,
  createFailure = null,
  createResult = {
    status: 200,
    envelope: { success: true, result: { item_ref: "ACM-23" } },
  },
} = {}) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "workflows.definition.get") {
        return definitionFailure || {
          status: 200,
          envelope: { success: true, result: { workflows } },
        };
      }
      if (request.function === "qa.plan.list") {
        return planFailure || {
          status: 200,
          envelope: { success: true, result: { rows: plans } },
        };
      }
      if (request.function === "qa.method.list") {
        return {
          status: 200,
          envelope: { success: true, result: { rows: methods } },
        };
      }
      if (request.function === "items.create") {
        if (createFailure) throw createFailure;
        return createResult;
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

test("New item refuses missing fields and keeps a failed create editable", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const client = intakeClient({
    createResult: {
      status: 422,
      envelope: {
        success: false,
        error: { message: "instruction violates project policy" },
      },
    },
  });
  renderNewItemView(
    itemContext(documentNode, client.call.bind(client)),
    root,
    "7",
  );
  await settle();

  const form = allNodes(root).find((node) => node.tagName === "FORM");
  form.dispatchEvent(new Event("submit"));
  assert.equal(
    byClass(root, "item-form-outcome")[0].textContent,
    "Title and instruction are required.",
  );
  assert.equal(
    client.requests.some((request) => request.function === "items.create"),
    false,
  );

  const input = allNodes(root).find((node) => node.tagName === "INPUT");
  const textarea = allNodes(root).find((node) => node.tagName === "TEXTAREA");
  input.value = "Fix the footer";
  textarea.value = "Correct the footer and verify every link.";
  form.dispatchEvent(new Event("submit"));
  await settle();
  assert.equal(
    byClass(root, "item-form-outcome")[0].textContent,
    "instruction violates project policy",
  );
  assert.equal(
    allNodes(root).find(
      (node) => node.tagName === "BUTTON" &&
        node.textContent === "Create Dash",
    ).disabled,
    false,
  );
});

test("New item explains an empty QA catalog and cannot enable verification", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const client = intakeClient({
    workflows: [dashWorkflow(["verification"])],
  });
  renderNewItemView(
    itemContext(documentNode, client.call.bind(client)),
    root,
    "7",
  );
  await settle();

  const row = byClass(root, "item-setting-row")[0];
  assert.match(itemText(row), /no plans or ad hoc methods are available/);
  const toggle = byClass(row, "item-button")[0];
  assert.equal(toggle.disabled, true);
  toggle.dispatchEvent(new Event("click"));
  assert.equal(toggle.attributes.get("aria-pressed"), "false");
  assert.equal(byClass(root, "item-setting-select").length, 0);
});

test("New item distinguishes no web workflow from registry and catalog failures", async () => {
  const cases = [
    {
      client: intakeClient({
        workflows: [{
          id: "issue",
          name: "Issue",
          definition: {
            entry_surfaces: ["harness_skill"],
            policies: { item_posture_allowlist: [] },
          },
        }],
      }),
      expected:
        "No current workflow version allows the web form entry surface.",
    },
    {
      client: intakeClient({
        definitionFailure: {
          status: 503,
          envelope: {
            success: false,
            error: { message: "workflow registry unavailable" },
          },
        },
      }),
      expected: "read failed (HTTP 503): workflow registry unavailable",
    },
    {
      client: intakeClient({
        planFailure: {
          status: 502,
          envelope: {
            success: false,
            error: { message: "QA catalog unavailable" },
          },
        },
      }),
      expected: "read failed (HTTP 502): QA catalog unavailable",
    },
  ];
  for (const entry of cases) {
    const documentNode = new FakeDocument();
    const root = documentNode.createElement("div");
    renderNewItemView(
      itemContext(documentNode, entry.client.call.bind(entry.client)),
      root,
      "7",
    );
    await settle();
    assert.ok(itemText(root).includes(entry.expected));
    assert.equal(allNodes(root).some((node) => node.tagName === "FORM"), false);
  }
});

test("New item surfaces transport failures during load and create", async () => {
  const loadDocument = new FakeDocument();
  const loadRoot = loadDocument.createElement("div");
  renderNewItemView(itemContext(loadDocument, async (request) => {
    if (request.function === "workflows.definition.get") {
      throw new Error("registry connection lost");
    }
    return {
      status: 200,
      envelope: { success: true, result: { rows: [] } },
    };
  }), loadRoot, "7");
  await settle();
  assert.match(itemText(loadRoot), /registry connection lost/);
  assert.equal(
    allNodes(loadRoot).some((node) => node.tagName === "FORM"),
    false,
  );

  const createDocument = new FakeDocument();
  const createRoot = createDocument.createElement("div");
  const client = intakeClient({
    createFailure: new Error("create connection lost"),
  });
  renderNewItemView(
    itemContext(createDocument, client.call.bind(client)),
    createRoot,
    "7",
  );
  await settle();
  const input = allNodes(createRoot).find((node) => node.tagName === "INPUT");
  const textarea = allNodes(createRoot).find(
    (node) => node.tagName === "TEXTAREA",
  );
  input.value = "Fix the footer";
  textarea.value = "Correct the footer and verify every link.";
  allNodes(createRoot).find((node) => node.tagName === "FORM")
    .dispatchEvent(new Event("submit"));
  await settle();
  assert.match(itemText(createRoot), /create connection lost/);
  assert.equal(
    allNodes(createRoot).find(
      (node) => node.tagName === "BUTTON" &&
        node.textContent === "Create Dash",
    ).disabled,
    false,
  );
});
