import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  shownDeliveryRuns,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_item_deployment.js";
import {
  FakeDocument,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { workbenchClient } from "./universe_ui_workbench_test_support.mjs";

const MINUTE = 60 * 1000;
const ago = (minutes) => new Date(Date.now() - minutes * MINUTE).toISOString();

function run(id, status, minutes, facts = {}) {
  return {
    id,
    status,
    target_environment: "prod",
    created_at: ago(minutes),
    completed_at: status === "succeeded" || status === "failed"
      ? ago(minutes - 1)
      : "",
    ...facts,
  };
}

test("the newest failed run remains visible over an older success", () => {
  const shown = shownDeliveryRuns([
    run("run-succeeded", "succeeded", 60),
    run("run-failed", "failed", 20),
  ]);

  assert.deepEqual(shown.map(({ id }) => id), ["run-failed"]);
});

test("a newer success supersedes the environment's older failure", () => {
  const shown = shownDeliveryRuns([
    run("run-failed", "failed", 60),
    run("run-succeeded", "succeeded", 20),
  ]);

  assert.deepEqual(shown.map(({ id }) => id), ["run-succeeded"]);
});

test("an in-flight run older than thirty minutes is labeled delayed", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const itemId = 3376;
  const client = workbenchClient({
    "items.overview.list": {
      rows: [{
        internal_id: itemId,
        public_ref: "YOK-3376",
        project: "yoke",
        project_id: 1,
        project_sequence: 3376,
        title: "Show delayed runs",
        workflow_id: "dash",
        status: "release",
        completion_flow: "flow",
        completion_flow_source: "item",
        delivery: { merges: 1, deployed: 0, not_deployed: 1 },
        created_at: ago(90),
      }],
    },
    "frontier.list": { ready_rows: [], blocked_rows: [] },
    "sessions.list": { rows: [] },
    "deployment_runs.list": {
      rows: [{
        ...run("run-delayed", "executing", 45),
        project: "yoke",
        flow: "flow",
        stages: [],
        member_items: [{ id: itemId, ref: "YOK-3376", title: "Show delayed runs" }],
      }],
    },
  });
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/frontier?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  t.after(() => mounted.unmount());
  await settle();

  assert.match(
    byClass(root, "item-deployment-time")[0].textContent,
    /^Deployment delayed · started .+ ago$/,
  );
});
