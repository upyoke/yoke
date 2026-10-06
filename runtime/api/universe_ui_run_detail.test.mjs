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
      ref: "YOK-2228", project_sequence: 2228,
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
        return okEnvelope({ rows: [
          { id: 1, slug: "yoke", name: "Yoke" },
          { id: 2, slug: "platform", name: "Platform" },
        ] });
      }
      if (request.function === "deployment_runs.list") {
        const selected = request.payload.page?.projects;
        const visible = selected
          ? row?.member_items.filter((item) => selected.includes(String(item.project_id)))
          : row?.member_items;
        return okEnvelope({
          rows: row ? [{ ...row, member_items: visible }] : [],
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
          rows: request.payload.public_refs ? itemActivityRows : activityRows,
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
          public_ref: request.target.public_ref,
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
  documentNode.defaultView.location.href = hash || "/";
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
      request_id: gate.id, kind: gate.kind,
      subject_context: { ...gate.subject_context,
        evidence: { screenshots: [{ id: 41, artifact_type: "screenshot",
          content_type: "image/png" }] } },
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
  const { root, mounted } = await mountAt(t, "/deployments/runs/run-20260726-001?project=1", client);

  // One run, found by its id through the same paged read the table uses.
  const read = client.requests.find((request) => request.function === "deployment_runs.list");
  assert.deepEqual(read.payload, {
    page: { page_size: 50, search: "run-20260726-001" },
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
    Array.isArray(payload.public_refs) && payload.public_refs.includes("YOK-2228")
  )), JSON.stringify(activity));

  // The trail stands on its own line above the title, and the run's own id
  // is not repeated: the breadcrumb already ends on it.
  const head = byClass(root, "run-head")[0];
  assert.ok(head.children[0].classList.contains("breadcrumb"));
  assert.equal(
    byClass(head, "breadcrumb-here")[0].textContent, "run-20260726-001",
  );
  assert.equal(byClass(root, "run-title")[0].textContent, "Hosted release");
  assert.equal(
    byClass(root, "run-sub")[0].textContent,
    "yoke · prod · 1 item · release 0.1.1+launch · awaiting approval",
  );
  // The status badge ends the facts line rather than floating by the title.
  const facts = byClass(root, "run-sub")[0];
  assert.equal(facts.children.at(-1), byClass(root, "run-badge")[0]);
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
  assert.equal(identityValues[1], "No artifact identity recorded; this run pins a source revision.");
  assert.equal(identityValues[2], "not frozen");
  assert.equal(identityValues[3], "prod · https://upyoke.com");
  const qa = byClass(root, "run-qa-section")[0];
  assert.equal(byClass(qa, "run-verdict")[0].textContent, "1 of 1 passed");
  // A check is named for its method, never its case key.
  assert.equal(byClass(qa, "run-qa-check-name")[0].textContent, "Browser check");
  assert.equal(byClass(qa, "review-shot").length, 1);
  // The decision: what the run carries, and the request folded in.
  const decision = byClass(root, "run-work")[0];
  assert.ok(decision.textContent.includes("Waiting for approval"), decision.textContent);
  const items = byClass(decision, "run-items")[0].children;
  assert.equal(items[0].textContent, "YOK-2228");
  assert.equal(items[1].textContent, "Ship the release");
  assert.equal(byClass(decision, "carried-item-evidence").length, 0);
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
  const { root, mounted } = await mountAt(t, "/deployments/runs/run-20260726-001?project=1", client);
  assert.equal(byClass(root, "run-badge")[0].textContent, "succeeded");
  // Stages beside the work, run QA below the carried items.
  const decision = byClass(root, "run-work")[0];
  assert.ok(decision.textContent.includes("Succeeded"), decision.textContent);
  assert.ok(decision.textContent.includes("Completed now."), decision.textContent);
  assert.equal(byClass(decision, "review-card").length, 0);
  assert.ok(byClass(root, "run-top")[0].children.includes(decision));
  assert.ok(byClass(root, "run-stages")[0]);
  // A run with no run checks and no decision has no Run QA section at all.
  assert.equal(byClass(root, "run-qa-section").length, 0);
  assert.doesNotMatch(root.textContent, /No run checks were recorded/);
  mounted.unmount();
});

for (const route of [
  "/deployments/runs/run-20260726-001?selection=all",
  "/deployments/runs/run-20260726-001?project=1",
]) {
  test(`a mixed-project run shows every authorized member from ${route}`, async (t) => {
    const yokeRef = ["YOK", 2228].join("-");
    const platformRef = ["PLAT", 149].join("-");
    const client = runClient(runRow({
      member_items: [
        { id: 2262, ref: yokeRef, project_sequence: 2228,
          title: "Ship the release", project_id: 1, project: "yoke" },
        { id: 2263, ref: platformRef, project_sequence: 149,
          title: "Build the host", project_id: 2, project: "platform" },
      ],
    }));
    const { root, mounted } = await mountAt(t, route, client);
    const read = client.requests.find((request) => request.function === "deployment_runs.list");
    assert.deepEqual(read.payload.page, { page_size: 50, search: "run-20260726-001" });
    assert.equal(byClass(root, "run-sub")[0].textContent,
      "yoke · prod · 2 items · release 0.1.1+launch · executing");
    assert.deepEqual(byClass(root, "carried-item-ref").map((node) => node.textContent),
      [yokeRef, platformRef]);
    // Each carried title links to the same item as its reference.
    assert.deepEqual(byClass(root, "carried-item-title").map((node) => [
      node.tagName, node.textContent, node.href]), [
      ["A", "Ship the release", "/items/YOK-2228?project=1"],
      ["A", "Build the host", "/items/PLAT-149?project=2"],
    ]);
    assert.equal(byClass(root, "run-fact-value")[0].textContent, "0.1.1+launch.379");
    assert.equal(byClass(root, "run-items")[0].children.find(
      (node) => node.textContent === platformRef).href, "/items/PLAT-149?project=2");
    assert.ok(client.requests.some((request) => request.function === "qa.activity.list"
      && request.payload.project === "1" && request.payload.deployment_run_id));
    assert.ok(client.requests.some((request) => request.function === "qa.activity.list"
      && request.payload.project === "2" && request.payload.public_refs?.includes(platformRef)));
    mounted.unmount();
  });
}

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
    t, "/deployments/runs/run-20260726-001?project=1", client,
  );

  // No boilerplate about what a stopped run's evidence answers for.
  assert.doesNotMatch(root.textContent, /evidence answers for this candidate only/);
  // The run itself is not listed as its own replacement.
  const siblings = byClass(root, "run-sibling");
  assert.deepEqual(
    siblings.map((node) => node.children[0].textContent), ["run-20260726-004"],
  );
  assert.equal(
    siblings[0].children[0].href, "/deployments/runs/run-20260726-004?project=1",
  );
  mounted.unmount();
});

test("an inaccessible or missing run says so rather than drawing an empty page", async (t) => {
  const client = runClient(null);
  const { root, mounted } = await mountAt(t, "/deployments/runs/run-nope?project=1", client);
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.match(text, /There is no accessible run called run-nope/);
  assert.equal(byClass(root, "review-link")[0].href, "/deployments/runs?project=1");
  mounted.unmount();
});

test("a run page leaves run-less item QA on the item", async (t) => {
  const client = runClient(runRow(), [], [{
    requirement_id: 26134, deployment_run_id: null, public_ref: "YOK-2228",
    method_name: "Browser inspection", outcome: "undetermined", artifacts: [],
  }]);
  const { root } = await mountAt(t, "/deployments/runs/run-20260726-001?project=1", client);
  await settle();
  assert.equal(byClass(byClass(root, "run-items")[0], "carried-item-evidence").length, 0);
});
