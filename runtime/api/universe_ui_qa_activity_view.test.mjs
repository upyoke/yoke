import assert from "node:assert/strict";
import test from "node:test";

import { renderEvidence } from "../../packages/yoke-core/src/yoke_core/ui/static/qa_view_evidence.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { ok } from "./universe_ui_qa_view_data_test_support.mjs";
import { mountAt } from "./universe_ui_qa_view_test_support.mjs";

test("Evidence view actions expose local and stranded dispositions honestly", async () => {
  const documentNode = new FakeDocument();
  const requests = [];
  const context = {
    document: documentNode,
    client: {
      async call(request) {
        requests.push(request);
        return ok(request.payload.artifact_id === 4
          ? {
              artifact_id: 4,
              disposition: "evidence_on_machine",
              machine: "Test Mac",
              detail: "Open this evidence from its capture machine.",
            }
          : {
              artifact_id: 5,
              disposition: "evidence_not_portable",
              detail: "The artifact handle survived, but its bytes did not.",
            });
      },
    },
  };
  const host = documentNode.createElement("div");
  host.appendChild(renderEvidence(context, {
    cases: [{
      case_key: "marketing-pages-visual",
      last_result: {
        requirement_id: 32,
        evidence: [
          {
            id: 4,
            artifact_type: "screenshot",
            content_type: "image/png",
            artifact_handle:
              "{\"backend\":\"local\",\"path\":\"footer-strip.png\"}",
          },
          {
            id: 5,
            artifact_type: "screenshot",
            content_type: "image/png",
            artifact_handle:
              "{\"backend\":\"s3\",\"key\":\"checkout-summary.png\"}",
          },
        ],
      },
    }],
  }));

  assert.match(
    allNodes(host).map((node) => node.textContent).join(" "),
    /Evidence · marketing-pages-visual/,
  );
  const actions = byClass(host, "qa-evidence-action");
  assert.deepEqual(actions.map((node) => node.textContent), ["view →", "view →"]);
  actions[0].dispatchEvent(new Event("click"));
  await settle();
  actions[1].dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    actions.map((node) => node.textContent),
    ["on Test Mac", "not portable"],
  );
  assert.deepEqual(
    requests.map((request) => request.target),
    [
      { kind: "qa_requirement", qa_requirement_id: 32 },
      { kind: "qa_requirement", qa_requirement_id: 32 },
    ],
  );
});

test("Activity folds hidden QA plumbing into readable outcomes", async (t) => {
  const { root, client, mounted } = await mountAt(
    t, "#/qa/activity?project=1",
  );

  assert.equal(byClass(root, "qa-stat").length, 4);
  assert.deepEqual(
    byClass(root, "qa-stat").map(
      (card) => card.children.map((node) => node.textContent),
    ),
    [
      ["10", "case runs today"],
      ["8", "passed"],
      ["1", "needs review"],
      ["1", "running"],
    ],
  );
  assert.equal(byClass(root, "qa-clickable-row").length, 6);
  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "qa.activity.list",
    ),
    {
      function: "qa.activity.list",
      payload: { project: "1", limit: 6 },
    },
  );
  const text = allNodes(root).map((node) => node.textContent).join(" ");
  assert.match(text, /case runs today/);
  assert.match(text, /release-readiness/);
  assert.match(text, /checkout-flow/);
  assert.match(text, /Browser check/);
  assert.match(text, /needs review/);
  assert.match(text, /4 screenshots/);
  assert.doesNotMatch(text, /4 artifacts/);
  assert.deepEqual(
    byClass(root, "qa-outcome").map((node) => node.children[0].textContent),
    [
      "needs review",
      "running",
      "passed · capture degraded",
      "passed",
      "passed",
      "blocked on precondition",
    ],
  );
  assert.equal(byClass(root, "qa-outcome-reason").length, 0);
  assert.equal(
    text.match(/image capture blocked on the host/g)?.length,
    1,
  );
  assert.equal(
    text.match(/capability went error/g)?.length,
    1,
  );
  assert.match(
    text,
    /Blocked on precondition is neither a pass nor a case failure — the case's host baseline could not be reached or verified\./,
  );
  mounted.unmount();
});
