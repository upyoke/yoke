// Who holds an item is a fact about the item, so every detail shape shows the
// holder's own session card — and shows it only while the claim is live.

import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemDetailView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import {
  FakeDocument,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  detailItem,
  itemContext,
  itemText,
} from "./universe_ui_items_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

const HOLDER = {
  session_id: "session-z",
  executor: "codex-cli",
  project_id: 7,
  liveness: "active",
  mode: "dash",
  holdings: { current: [] },
};

function client(item, { rows = [HOLDER] } = {}) {
  return async (request) => {
    if (request.function === "items.detail.get") return ok({ item });
    if (request.function === "sessions.list") return ok({ rows });
    if (request.function === "deployment_runs.find_by_item") {
      return ok({ item_id: 51, fields: [], rows: [] });
    }
    if (request.function === "qa.artifact.read") {
      return ok({ disposition: "unavailable" });
    }
    if (request.function === "inbox.list") return ok({ needs_decision: [] });
    if (request.function === "epic_tasks.list.run") return ok({ tasks: [] });
    if (request.function === "strategy.execution.get") {
      return ok({ execution: { execution_document: { slug: "PLAN" } } });
    }
    throw new Error(`unexpected function ${request.function}`);
  };
}

async function renderWorkflow(workflowId, options = {}) {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const item = detailItem(workflowId);
  if (options.mutate) options.mutate(item);
  renderItemDetailView(
    itemContext(documentNode, client(item, options)), root, "7", "ACM-22",
  );
  await settle();
  await settle();
  return root;
}

// Every workflow an item can pin, including the laneless floor shape: a Task
// is claimed like anything else, and its holder is the same question.
for (const workflowId of ["issue", "epic", "dash", "task", "blitz"]) {
  test(`a claimed ${workflowId} item shows its holder's session card`, async () => {
    const root = await renderWorkflow(workflowId);

    assert.equal(byClass(root, "session-card").length, 1);
    assert.equal(
      byClass(root, "session-card")[0].attributes.get("data-session-id"),
      "session-z",
    );
    assert.match(itemText(root), /Claimed by/);
  });
}

test("an unclaimed item draws no holder panel rather than an empty one", async () => {
  const root = await renderWorkflow("dash", {
    mutate: (item) => { item.claim = null; },
  });

  assert.equal(byClass(root, "session-card").length, 0);
  assert.doesNotMatch(itemText(root), /Claimed by/);
});

test("a claim naming a session the roster does not hold says so", async () => {
  // The roster answers for live sessions in this project; a claim pointing at
  // one it does not carry is reported, never drawn from the claim row alone.
  const root = await renderWorkflow("dash", { rows: [] });

  assert.equal(byClass(root, "session-card").length, 0);
  assert.match(itemText(root), /Codex holds this item through session session-z/);
  assert.match(itemText(root), /roster does not hold/);
});
