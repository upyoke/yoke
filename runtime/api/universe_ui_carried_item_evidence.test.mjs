// What a release's carried items prove, seen from the deployment card that
// carries them.
//
// A run's own checks record the run they ran in; an item-attached
// requirement records no deployment run at all. Grouping QA activity by run
// therefore dropped an item's own evidence entirely, and a release card
// listing that item showed nothing beside it — the live case was three
// uploaded screenshots that no deployment surface would draw. These cases
// hold the shape that replaced it: evidence read for the items on screen,
// shown in each item's own Carries entry, labelled honestly when it says
// nothing about this run, and a waiting review answered right there through
// the request the Inbox would have answered.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";
import { qaRequestRow } from "./universe_ui_inbox_test_support.mjs";
import { overviewRunCard } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_overview_cards.js";
import {
  carriedItemEvidence,
  loadCarriedItemEvidence,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";

const RUN_ID = "run-20260910-009";
const PNG = "iVBORw0KGgo=";

function artifact(id, requirementId) {
  return {
    id,
    artifact_type: "screenshot",
    content_type: "image/png",
    requirement_id: requirementId,
    metadata: { label: `shot-${id}`, step_index: id },
  };
}

function activityRow(overrides = {}) {
  return {
    requirement_id: 26134,
    run_id: 28095,
    deployment_run_id: null,
    deployment_stage: null,
    item_id: 1896,
    deployment_member_item_id: null,
    plan_id: 7,
    plan: "release-readiness",
    project: "yoke",
    case_key: "marketing-pages-visual",
    method_name: "Browser inspection",
    outcome: "undetermined",
    artifacts: [artifact(17882, 26134), artifact(17883, 26134)],
    evidence_count: 2,
    happened_at: "2026-09-10T09:00:00Z",
    ...overrides,
  };
}

function runRow(items) {
  return {
    id: RUN_ID,
    project: "yoke",
    status: "failed",
    flow: "yoke-hosted-stage-consumer-bound",
    target_environment: "stage",
    created_at: "2026-09-10T10:00:00Z",
    stages: [{ name: "release", state: "failed" }],
    gates: [],
    member_items: items,
  };
}

function member(id, ref, overrides = {}) {
  return {
    id,
    ref,
    title: `${ref} title`,
    project_id: 1,
    project_sequence: id,
    ...overrides,
  };
}

// A client that answers the two reads the carried-item evidence needs, and
// records every request so a case can assert what was actually asked for.
function readingClient({ rows = [], pending = [], resolves = [] } = {}) {
  const requests = [];
  return {
    requests,
    resolves,
    async call(request) {
      requests.push(request);
      if (request.function === "qa.activity.list") {
        const wanted = new Set((request.payload.item_ids || []).map(Number));
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: rows.filter((row) => wanted.has(
                Number(row.item_id ?? row.deployment_member_item_id),
              )),
              summary: { day: "2026-09-10", total: rows.length, counts: {} },
            },
          },
        };
      }
      if (request.function === "inbox.list") {
        return {
          status: 200,
          envelope: { success: true, result: { needs_decision: pending } },
        };
      }
      if (request.function === "decision_requests.resolve") {
        resolves.push(request.payload);
        return { status: 200, envelope: { success: true, result: {} } };
      }
      if (request.function === "qa.artifact.read") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              disposition: "ready",
              content_type: "image/png",
              content_base64: PNG,
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

function readingContext(documentNode, client) {
  return {
    document: documentNode,
    capabilities: {},
    client,
    isMounted: () => true,
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
  };
}

async function cardFor(documentNode, items, client, onItemDecision = null) {
  const context = readingContext(documentNode, client);
  const itemFacts = await loadCarriedItemEvidence(context, items);
  return {
    itemFacts,
    card: overviewRunCard(context, runRow(items), ["1"], {
      facts: { evidence: new Map(), flowNames: new Map(), failed: null },
      itemFacts,
      onItemDecision,
    }),
  };
}

function memberEntry(card, index = 0) {
  return byClass(card, "overview-run-member")[index];
}

test("evidence is read for the carried items, not for whatever is recent", async () => {
  const client = readingClient({ rows: [activityRow()] });
  const context = readingContext(new FakeDocument(), client);

  await loadCarriedItemEvidence(context, [
    member(1896, "BUZ-1896"), member(1900, "BUZ-1900"),
  ]);

  const activity = client.requests.find((r) => r.function === "qa.activity.list");
  assert.deepEqual(activity.payload.item_ids, [1896, 1900]);
  assert.equal(activity.payload.project, "1");
});

test("an item's own QA shows in its Carries entry, labelled as not this run's proof", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({ rows: [activityRow()] });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const entry = memberEntry(card);
  assert.match(entry.textContent, /BUZ-1896/);
  const evidence = byClass(entry, "carried-item-evidence")[0];
  assert.ok(evidence, "the item's entry carries its own evidence");
  assert.match(
    byClass(evidence, "carried-item-evidence-caption")[0].textContent,
    /1 check · 1 undetermined/,
  );
  // Each screenshot is its own control inside that entry.
  assert.equal(byClass(evidence, "review-shot").length, 2);
  // A record with no deployment run is item evidence, and says so rather
  // than standing in for a verdict this failed run never earned.
  assert.match(
    byClass(evidence, "carried-item-evidence-note")[0].textContent,
    /no deployment run — item evidence, not proof of this run\./,
  );
});

test("each carried item shows its own evidence and no one else's", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [
      activityRow(),
      activityRow({
        requirement_id: 26140,
        item_id: 1900,
        outcome: "passed",
        deployment_run_id: RUN_ID,
        deployment_stage: "stage",
        artifacts: [artifact(17890, 26140)],
      }),
    ],
  });
  const { card } = await cardFor(
    documentNode, [member(1896, "BUZ-1896"), member(1900, "BUZ-1900")], client,
  );
  await settle();

  const first = byClass(memberEntry(card, 0), "carried-item-evidence")[0];
  const second = byClass(memberEntry(card, 1), "carried-item-evidence")[0];
  assert.equal(byClass(first, "review-shot").length, 2);
  assert.equal(byClass(second, "review-shot").length, 1);
  // The check recorded against this very run needs no disclaimer.
  assert.match(
    byClass(second, "carried-item-evidence-caption")[0].textContent, /1 passed/,
  );
  assert.equal(byClass(second, "carried-item-evidence-note").length, 0);
});

test("evidence recorded against another run stays with that run", () => {
  const facts = {
    byItem: new Map([["1896", [
      activityRow({ deployment_run_id: "run-20260910-003" }),
      activityRow({ requirement_id: 26141, deployment_run_id: RUN_ID }),
    ]]]),
    pendingByRequirement: new Map(),
    failed: null,
  };

  const shown = carriedItemEvidence(facts, 1896, RUN_ID);
  assert.deepEqual(shown.checks.map((check) => check.requirement_id), [26141]);
  assert.equal(shown.unlinked, 0);
});

test("a run carrying nothing draws no carries box and no item evidence", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({ rows: [activityRow()] });
  const { card } = await cardFor(documentNode, [], client);
  await settle();

  assert.equal(byClass(card, "overview-run-batch").length, 0);
  assert.equal(byClass(card, "carried-item-evidence").length, 0);
  // Nothing to read evidence for means nothing is asked of the server.
  assert.deepEqual(client.requests, []);
});

test("a waiting review is answered from the item's entry, as the Inbox would", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [activityRow()],
    pending: [qaRequestRow({
      id: 4400,
      status: "pending",
      subject_key: "26134",
      subject_context: {
        ...qaRequestRow().subject_context, requirement_id: 26134,
      },
    })],
  });
  const answered = [];
  const { card } = await cardFor(
    documentNode,
    [member(1896, "BUZ-1896")],
    client,
    (request, action) => answered.push([request.id, action]),
  );
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  const review = byClass(evidence, "review-card")[0];
  assert.ok(review, "the waiting review is offered inside the item's entry");
  assert.equal(review.getAttribute("data-request-id"), "4400");
  // Its evidence is the strip above it, not a second copy inside the card.
  assert.equal(byClass(review, "review-evidence").length, 0);
  const approve = byClass(evidence, "review-action").find(
    (button) => button.getAttribute("data-action") === "approve",
  );
  approve.dispatchEvent(new Event("click"));
  assert.deepEqual(answered, [[4400, "approve"]]);
});

test("a failed verdict with no waiting request offers no decision", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [activityRow({ outcome: "failed" })],
    // The reader already answered this one, so the server still lists it and
    // it is nobody's waiting work.
    pending: [qaRequestRow({
      id: 4401,
      status: "resolved",
      decided_by_you: true,
      subject_context: {
        ...qaRequestRow().subject_context, requirement_id: 26134,
      },
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  assert.ok(evidence, "its evidence is still shown");
  assert.equal(byClass(evidence, "review-card").length, 0);
  assert.equal(byClass(evidence, "review-action").length, 0);
});

test("a review belonging to another item is not offered under this one", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [activityRow()],
    pending: [qaRequestRow({
      id: 4402,
      status: "pending",
      subject_key: "31000",
      subject_context: {
        ...qaRequestRow().subject_context, requirement_id: 31000,
      },
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  assert.equal(byClass(evidence, "review-card").length, 0);
});
