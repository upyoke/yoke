// The run page: one deployment run in the page's shape, reached from a
// Deployments row, a Shipping card, or a release request.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { deploymentRequestRow } from "./universe_ui_inbox_test_support.mjs";

const okEnvelope = (result) => ({ status: 200, envelope: { success: true, result } });

function runRow(overrides = {}) {
  return {
    id: "run-20260726-001", project: "yoke", flow: "hosted-release",
    target_tier: "persistent", target_environment: "prod",
    release_lineage: "0.1.1+launch.379", status: "executing",
    current_stage: "approval", created_at: "2026-07-26T10:00:00Z",
    started_at: null, completed_at: null, created_by: "usher",
    stages: [
      { name: "build", state: "complete" },
      { name: "approval", state: "active" },
      { name: "release", state: "pending" },
    ],
    member_items: [{
      id: 2262, ref: "YOK-2228", project_sequence: 2228,
      title: "Ship the release", project_id: 1, project: "yoke",
    }],
    gates: [],
    ...overrides,
  };
}

function runClient(row, activityRows = []) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return okEnvelope({ name: "Yoke" });
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "deployment_runs.list") {
        return okEnvelope({
          rows: row ? [row] : [],
          unfinished_count: row ? 1 : 0, completed_match_count: 0,
          completed_loaded_count: 0, next_cursor: null,
          filters: {
            projects: [], statuses: [], environments: [],
            flows: [{ id: "hosted-release", label: "Hosted release" }],
          },
        });
      }
      if (request.function === "qa.activity.list") {
        return okEnvelope({ summary: { total: 0, counts: {} }, rows: activityRows });
      }
      if (request.function === "qa.artifact.read") {
        return okEnvelope({
          artifact_id: request.payload.artifact_id, disposition: "ready",
          content_type: "image/png", content_base64: "aVZCT1J3MEs=",
        });
      }
      if (request.function === "decision_requests.resolve") {
        return okEnvelope({ request: { id: request.payload.request_id, status: "resolved" } });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountAt(t, hash, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  await settle();
  return { root, mounted };
}

test("the run page reads the run by id and draws it in the page's shape", async (t) => {
  const gate = deploymentRequestRow();
  const client = runClient(runRow({
    gates: [{
      request_id: gate.id, kind: gate.kind, subject_context: gate.subject_context,
      actions: gate.actions, approval_progress: {}, can_act: true,
      authority_reason: "project owner", deciders: gate.deciders,
      your_decision: null, decided_by_you: false,
    }],
  }), [{
    requirement_id: 9, deployment_run_id: "run-20260726-001", plan_id: 7,
    plan: "release-readiness", project: "yoke", case_key: "smoke",
    method_name: "Browser check", outcome: "passed", evidence_count: 1,
    happened_at: "2026-07-26T10:05:00Z",
    artifacts: [{ id: 41, artifact_type: "screenshot", content_type: "image/png" }],
  }]);
  const { root, mounted } = await mountAt(t, "#/deployments/run-20260726-001?project=1", client);

  // One run, found by its id through the same paged read the table uses.
  const read = client.requests.find((request) => request.function === "deployment_runs.list");
  assert.deepEqual(read.payload, {
    page: { page_size: 50, search: "run-20260726-001", projects: ["1"] },
  });
  const activity = client.requests.find((request) => request.function === "qa.activity.list");
  assert.deepEqual(activity.payload, {
    project: "1", deployment_run_id: "run-20260726-001", limit: 100,
  });

  assert.equal(byClass(root, "run-eyebrow")[0].textContent, "yoke · prod");
  assert.equal(byClass(root, "run-title")[0].textContent, "Hosted release");
  assert.equal(
    byClass(root, "run-sub")[0].textContent,
    "1 item · release 0.1.1+launch · run-20260726-001",
  );
  assert.equal(byClass(root, "run-badge")[0].textContent, "awaiting approval");
  assert.deepEqual(
    byClass(root, "run-step").map((node) => node.className),
    ["run-step is-complete", "run-step is-active", "run-step is-pending"],
  );
  // Verification: the run's own checks, with their pictures.
  const verification = byClass(root, "run-card")[0];
  assert.equal(byClass(verification, "run-verdict")[0].textContent, "1 of 1 passed");
  assert.ok(byClass(verification, "run-check")[0].textContent.includes("smoke · Browser check"));
  assert.equal(byClass(verification, "review-shot").length, 1);
  // The decision: what the run carries, and the request folded in.
  const decision = byClass(root, "run-card")[1];
  assert.ok(decision.textContent.includes("Waiting for approval"), decision.textContent);
  assert.deepEqual(
    byClass(decision, "run-items")[0].children.map((node) => node.textContent),
    ["YOK-2228", "Ship the release"],
  );
  assert.equal(byClass(decision, "run-request-kind")[0].textContent, "Release approval");
  assert.deepEqual(
    byClass(decision, "review-action").map((node) => node.textContent),
    ["Reject", "Approve"],
  );
  byClass(decision, "review-action")[1].dispatchEvent(new Event("click"));
  await settle();
  const resolve = client.requests.find((request) => request.function === "decision_requests.resolve");
  assert.deepEqual(resolve.payload, { request_id: gate.id, action: "approve" });
  mounted.unmount();
});

test("a run with nothing waiting says what it is doing instead", async (t) => {
  const client = runClient(runRow({
    status: "succeeded", current_stage: "complete",
    completed_at: new Date(Date.now() - 3600_000).toISOString(),
    stages: [{ name: "build", state: "complete" }, { name: "release", state: "complete" }],
  }));
  const { root, mounted } = await mountAt(t, "#/deployments/run-20260726-001?project=1", client);
  assert.equal(byClass(root, "run-badge")[0].textContent, "succeeded");
  const decision = byClass(root, "run-card")[1];
  assert.ok(decision.textContent.includes("Succeeded"), decision.textContent);
  assert.equal(byClass(decision, "review-card").length, 0);
  assert.ok(
    byClass(root, "run-card")[0].textContent.includes("No checks were recorded on this run."),
  );
  mounted.unmount();
});

test("a run the scope does not hold says so rather than drawing an empty page", async (t) => {
  const client = runClient(null);
  const { root, mounted } = await mountAt(t, "#/deployments/run-nope?project=1", client);
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.match(text, /There is no run called run-nope in this scope/);
  assert.equal(byClass(root, "review-link")[0].href, "#/deployments?project=1");
  mounted.unmount();
});
