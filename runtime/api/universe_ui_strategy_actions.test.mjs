import assert from "node:assert/strict";
import test from "node:test";

import {
  stateActionsPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/strategy_view_summary.js";
import {
  FakeDocument,
  allNodes,
  settle,
} from "./universe_ui_dom_test_support.mjs";

test("Strategy review approval resolves the pending decision request", async () => {
  const documentNode = new FakeDocument();
  const requests = [];
  let refreshes = 0;
  const context = {
    document: documentNode,
    client: {
      async call(request) {
        requests.push(request);
        return {
          status: 200,
          envelope: {
            success: true,
            result: { request_id: 7, status: "approved" },
          },
        };
      },
    },
  };
  const panel = stateActionsPanel(
    context,
    "1",
    {
      slug: "WORKFLOW-TYPES",
      current_revision: 2,
      pending_review_count: 1,
      review_requests: [{ id: 7, status: "pending" }],
      execution_claim: null,
      references: [],
    },
    () => { refreshes += 1; },
  );

  const approve = allNodes(panel).find(
    (node) => node.tagName === "BUTTON" &&
      node.textContent === "Approve revision 2",
  );
  approve.dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(requests, [{
    function: "decision_requests.resolve",
    payload: { request_id: 7, action: "approve" },
    target: { kind: "global", project_id: "1" },
  }]);
  assert.equal(refreshes, 1);
});
