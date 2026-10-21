// Deployment state labels read as plain English, with the environment name
// taken from the record. The Frontier's dependency cards and the compact
// delivery summary share one helper, so both are checked here per state and
// for two environment names.

import assert from "node:assert/strict";
import test from "node:test";

import { deliveryStateLabel } from "../../packages/yoke-core/src/yoke_core/ui/static/deployment_environment_copy.js";
import { frontierEdgeDeploy } from "../../packages/yoke-core/src/yoke_core/ui/static/frontier_dependency_model.js";
import { deliverySummary } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_item_deployment.js";

const EXPECTED = {
  prod: {
    live: "✓ Live in prod",
    deploying: "Deploying to prod",
    "not deployed": "Merged · not in prod yet",
    failed: "✗ Failed in prod",
  },
  staging: {
    live: "✓ Live in staging",
    deploying: "Deploying to staging",
    "not deployed": "Merged · not in staging yet",
    failed: "✗ Failed in staging",
  },
};

const REF = "EXT-7";

function summary(env, run, row = {}) {
  const runs = new Map([[REF, run ? [{ id: `run-${env}`, target_environment: env, ...run }] : []]]);
  return deliverySummary({ public_ref: REF, ...row }, runs);
}

for (const [env, labels] of Object.entries(EXPECTED)) {
  test(`${env}: the helper names each state in plain English`, () => {
    for (const [state, text] of Object.entries(labels)) {
      assert.equal(deliveryStateLabel(state, env), text);
    }
  });

  test(`${env}: a Frontier dependency card reads each edge state`, () => {
    for (const state of ["live", "deploying", "not deployed"]) {
      const edge = { env: { name: env, delivery_state: state, in_delivery_flow: true } };
      assert.equal(frontierEdgeDeploy(edge), labels[state]);
    }
  });

  test(`${env}: the compact delivery summary reads each run state`, () => {
    assert.equal(summary(env, null, {
      delivery: { completed_deliveries: [{ environment: env, run_id: `run-${env}` }] },
    }), labels.live);
    assert.equal(summary(env, { status: "executing" }), labels.deploying);
    assert.equal(summary(env, { status: "failed" }), labels.failed);
    assert.equal(summary(env, null, { completion_environment: env }), labels["not deployed"]);
  });
}

test("a record that names no environment drops the place, not the sentence", () => {
  assert.equal(deliveryStateLabel("live", ""), "✓ Live");
  assert.equal(deliveryStateLabel("not deployed", undefined), "Merged · not deployed yet");
  assert.equal(deliveryStateLabel("paused", "prod"), "prod paused");
});
