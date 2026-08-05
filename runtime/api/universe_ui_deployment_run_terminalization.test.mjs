import assert from "node:assert/strict";
import test from "node:test";

import {
  renderDeliveryRunsView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_delivery.js";
import {
  FakeDocument,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

test("active run terminalization requires a reason and uses shared authority", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  let status = "executing";
  const context = {
    document: documentNode,
    isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    client: {
      async call(request) {
        requests.push(request);
        if (request.function === "deployment_runs.list") {
          return ok({
            rows: [{
              id: "run-20260804-010",
              project: "yoke",
              target_env: "production",
              status,
              current_stage: "hosted-release",
              created_at: "2026-08-04T01:00:00Z",
              stages: [],
              member_items: [],
            }],
          });
        }
        if (request.function === "deployment_runs.terminalize") {
          status = request.payload.disposition;
          return ok({
            run_id: "run-20260804-010",
            prior_status: "executing",
            final_status: status,
          });
        }
        throw new Error(`unexpected function ${request.function}`);
      },
    },
  };

  renderDeliveryRunsView(context, main, "all");
  await settle();
  assert.equal(byClass(main, "delivery-run-terminalize").length, 1);
  byClass(main, "delivery-run-terminalize")[0].dispatchEvent(
    new Event("click"),
  );
  assert.equal(
    byClass(main, "deployment-terminalization-state")[0].textContent,
    "Current state: executing",
  );

  const confirm = byClass(main, "primary")[0];
  confirm.dispatchEvent(new Event("click"));
  assert.equal(
    byClass(main, "deployment-terminalization-error")[0].textContent,
    "Enter a reason before confirming.",
  );
  byClass(main, "deployment-terminalization-disposition")[0].value = "failed";
  byClass(main, "deployment-terminalization-reason")[0].value = (
    "Hosted workflow is no longer active"
  );
  confirm.dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(
    requests.find((request) => (
      request.function === "deployment_runs.terminalize"
    )),
    {
      function: "deployment_runs.terminalize",
      payload: {
        disposition: "failed",
        reason: "Hosted workflow is no longer active",
      },
      target: {
        kind: "workflow_run",
        workflow_run_id: "run-20260804-010",
      },
    },
  );
  assert.equal(byClass(main, "deployment-terminalization-dialog").length, 0);
  assert.equal(byClass(main, "delivery-run-terminalize").length, 0);
});

test("terminal runs do not expose the action", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const context = {
    document: documentNode,
    isMounted: () => true,
    projects: () => [],
    client: {
      async call() {
        return ok({ rows: [{
          id: "run-complete", status: "succeeded", stages: [],
          member_items: [], created_at: "2026-08-05T00:00:00Z",
        }] });
      },
    },
  };
  renderDeliveryRunsView(context, main, "all");
  await settle();
  assert.equal(byClass(main, "delivery-run-terminalize").length, 0);
});
