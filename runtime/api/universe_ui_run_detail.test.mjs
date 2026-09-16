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

function runClient(row, activityRows = [], itemActivityRows = [], siblingRows = []) {
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
        return okEnvelope({
          summary: { total: 0, counts: {} },
          rows: request.payload.item_ids ? itemActivityRows : activityRows,
        });
      }
      if (request.function === "inbox.list") {
        return okEnvelope({ needs_decision: [] });
      }
      if (request.function === "projects.infrastructure.list") {
        return okEnvelope({
          project: request.payload.project,
          sites: [],
          environments: [
            { site: "hosted", name: "prod", url: "https://upyoke.com",
              deploy_method: "workflow", health_check_url: null,
              last_deployed_at: "2026-07-26T10:20:00Z" },
          ],
        });
      }
      if (request.function === "deployment_runs.find_by_item") {
        return okEnvelope({
          item_id: request.target.item_id,
          fields: ["id", "status", "current_stage", "created_at"],
          rows: siblingRows,
        });
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
  const { root, mounted } = await mountAt(t, "#/deployments/runs/run-20260726-001?project=1", client);

  // One run, found by its id through the same paged read the table uses.
  const read = client.requests.find((request) => request.function === "deployment_runs.list");
  assert.deepEqual(read.payload, {
    page: { page_size: 50, search: "run-20260726-001", projects: ["1"] },
  });
  // Two QA reads, because the page reports two different facts: what this
  // run's own checks found, and what each carried item proved on its own —
  // which an item-attached requirement records against no run at all.
  const activity = client.requests.filter(
    (request) => request.function === "qa.activity.list",
  ).map((request) => request.payload);
  assert.ok(activity.some((payload) => (
    payload.deployment_run_id === "run-20260726-001" && payload.project === "1"
  )), JSON.stringify(activity));
  assert.ok(activity.some((payload) => (
    Array.isArray(payload.item_ids) && payload.item_ids.includes(2262)
  )), JSON.stringify(activity));

  // The trail, the run's name and the facts that place it are one row, and
  // the run's own id is not repeated: the breadcrumb already ends on it.
  const head = byClass(root, "run-head")[0];
  assert.ok(byClass(head, "breadcrumb")[0]);
  assert.equal(
    byClass(head, "breadcrumb-here")[0].textContent, "run-20260726-001",
  );
  assert.equal(byClass(root, "run-title")[0].textContent, "Hosted release");
  assert.equal(
    byClass(root, "run-sub")[0].textContent,
    "yoke · prod · 1 item · release 0.1.1+launch",
  );
  assert.equal(byClass(root, "run-badge")[0].textContent, "awaiting approval");
  assert.deepEqual(
    byClass(root, "run-step").map((node) => node.className),
    ["run-step is-complete", "run-step is-active", "run-step is-pending"],
  );
  // Identity: what this release is frozen to, and where it is going.
  const identity = byClass(root, "run-identity")[0];
  assert.deepEqual(
    byClass(identity, "run-fact-label").map((node) => node.textContent),
    ["Candidate", "Artifact", "Members frozen", "Target"],
  );
  const identityValues = byClass(identity, "run-fact-value")
    .map((node) => node.textContent);
  assert.equal(identityValues[0], "0.1.1+launch.379");
  assert.equal(identityValues[1], "not recorded");
  assert.equal(identityValues[2], "not frozen");
  assert.equal(identityValues[3], "prod · https://upyoke.com");
  // Verification: the run's own checks, with their pictures, full width
  // below the stage rail and the work beside it.
  const verification = byClass(root, "run-grid")[0].children[0];
  assert.equal(byClass(verification, "run-verdict")[0].textContent, "1 of 1 passed");
  assert.ok(byClass(verification, "run-check")[0].textContent.includes("smoke · Browser check"));
  assert.equal(byClass(verification, "review-shot").length, 1);
  // The decision: what the run carries, and the request folded in.
  const decision = byClass(root, "run-work")[0];
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
    completed_at: new Date().toISOString(),
    stages: [{ name: "build", state: "complete" }, { name: "release", state: "complete" }],
  }));
  const { root, mounted } = await mountAt(t, "#/deployments/runs/run-20260726-001?project=1", client);
  assert.equal(byClass(root, "run-badge")[0].textContent, "succeeded");
  // Stages beside the work, verification full width below them.
  const decision = byClass(root, "run-work")[0];
  assert.ok(decision.textContent.includes("Succeeded"), decision.textContent);
  assert.ok(decision.textContent.includes("Completed now."), decision.textContent);
  assert.equal(byClass(decision, "review-card").length, 0);
  assert.ok(byClass(root, "run-top")[0].children.includes(decision));
  assert.ok(byClass(root, "run-stages")[0]);
  assert.ok(
    byClass(root, "run-grid")[0].children[0].textContent
      .includes("No checks were recorded on this run."),
  );
  // A run that ended well carries no aftermath block.
  assert.equal(byClass(root, "run-aftermath").length, 0);
  mounted.unmount();
});

test("a cancelled run keeps its history and names what carried the work after", async (t) => {
  const client = runClient(
    runRow({ status: "cancelled", current_stage: "approval" }),
    [],
    [],
    [
      { id: "run-20260726-004", status: "succeeded", current_stage: "complete",
        created_at: "2026-07-26T12:00:00Z" },
      { id: "run-20260726-001", status: "cancelled", current_stage: "approval",
        created_at: "2026-07-26T10:00:00Z" },
    ],
  );
  const { root, mounted } = await mountAt(
    t, "#/deployments/runs/run-20260726-001?project=1", client,
  );

  const aftermath = byClass(root, "run-aftermath")[0];
  assert.match(aftermath.textContent, /does not undo what it already deployed/);
  // The run itself is not listed as its own replacement.
  const siblings = byClass(root, "run-sibling");
  assert.deepEqual(
    siblings.map((node) => node.children[0].textContent), ["run-20260726-004"],
  );
  assert.equal(
    siblings[0].children[0].href, "#/deployments/runs/run-20260726-004?project=1",
  );
  mounted.unmount();
});

test("a run the scope does not hold says so rather than drawing an empty page", async (t) => {
  const client = runClient(null);
  const { root, mounted } = await mountAt(t, "#/deployments/runs/run-nope?project=1", client);
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.match(text, /There is no run called run-nope in this scope/);
  assert.equal(byClass(root, "review-link")[0].href, "#/deployments/runs?project=1");
  mounted.unmount();
});

test("a carried item's own QA is shown beside that item, labelled as its own", async (t) => {
  // The item's requirement records no deployment run, which is exactly the
  // shape a run-keyed read drops. The page carries it under the item.
  const client = runClient(runRow(), [], [{
    requirement_id: 26134, run_id: 28095, deployment_run_id: null,
    deployment_stage: null, item_id: 2262, deployment_member_item_id: null,
    plan_id: 7, plan: "release-readiness", project: "yoke",
    case_key: "marketing-pages-visual", method_name: "Browser inspection",
    outcome: "undetermined", evidence_count: 1,
    happened_at: "2026-07-26T10:05:00Z",
    artifacts: [{ id: 17882, artifact_type: "screenshot", content_type: "image/png" }],
  }]);
  const { root } = await mountAt(t, "#/deployments/runs/run-20260726-001?project=1", client);
  await settle();

  const evidence = byClass(byClass(root, "run-items")[0], "carried-item-evidence")[0];
  assert.ok(evidence, "the carried item carries its own evidence");
  assert.match(
    byClass(evidence, "carried-item-evidence-caption")[0].textContent,
    /1 check · 1 undetermined/,
  );
  assert.equal(byClass(evidence, "review-shot").length, 1);
  assert.equal(byClass(evidence, "carried-item-evidence-note").length, 0);
});
