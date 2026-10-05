// A delivery card draws only its run-bound member evidence.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";
import { qaRequestRow } from "./universe_ui_inbox_test_support.mjs";
import {
  activityRow as unboundActivityRow,
  artifact,
  cardFor,
  deployedTarget,
  itemReviewRow,
  member,
  memberEntry,
  readingClient,
  readingContext,
  RUN_ID,
} from "./universe_ui_carried_item_test_support.mjs";
import {
  carriedItemEvidence,
  loadCarriedItemEvidence,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_carried_item_evidence.js";

const activityRow = (overrides = {}) => unboundActivityRow({
  deployment_run_id: RUN_ID, ...overrides,
});

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

test("an item's own QA shows in its Carries entry", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({ rows: [activityRow()] });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const entry = memberEntry(card);
  assert.match(entry.textContent, /BUZ-1896/);
  const evidence = byClass(entry, "carried-item-evidence")[0];
  assert.ok(evidence, "the item's entry carries its own evidence");
  const section = byClass(evidence, "item-qa-section")[0];
  assert.equal(byClass(section, "run-qa-head")[0].children[0].textContent, "Item QA");
  const row = byClass(section, "run-qa-check")[0];
  assert.equal(byClass(row, "run-qa-check-name")[0].children[0].href,
    "/qa-activity/26134?project=1");
  assert.equal(byClass(evidence, "run-qa-history").length, 0);
  // Each screenshot is its own control inside that entry.
  assert.equal(byClass(evidence, "review-shot").length, 2);
  // The distinction between an item's own record and this run's proof is
  // structural — item QA sits under the item, deployment verification sits
  // under the run — so the card no longer repeats it in a sentence on every
  // entry that has one.
  assert.equal(byClass(evidence, "carried-item-evidence-note").length, 0);
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
        execution_target_json: deployedTarget(),
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
  // The check this run recorded leads its entry as a current check, in the
  // run's own words and without restating the release the card is about.
  const lead = byClass(second, "item-qa-section")[0].children
    .find((node) => node.classList.contains("run-qa-check"));
  assert.equal(byClass(lead, "run-qa-check-name")[0].textContent, "Browser inspection");
  assert.equal(byClass(lead, "run-qa-check-outcome")[0].textContent, "Passed");
  assert.equal(byClass(lead, "run-qa-check-mark")[0].textContent, "✓");
  assert.doesNotMatch(second.textContent, /this release/);
  assert.equal(byClass(first, "item-qa-section")[0].children
    .filter((node) => node.classList.contains("run-qa-check")).length, 1);
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
});

test("a run carrying nothing draws no carries box and no item evidence", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({ rows: [activityRow()] });
  const { card } = await cardFor(documentNode, [], client);
  await settle();

  assert.equal(byClass(card, "release-batch").length, 0);
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
  const review = byClass(evidence, "run-request")[0];
  assert.ok(review, "the waiting review is offered inside the item's entry");
  assert.equal(review.getAttribute("data-request-id"), "4400");
  // The strip above is this item's recent history, which does not contain
  // the capture this request rests on, so the request still carries it.
  assert.equal(byClass(review, "review-evidence").length, 1);
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
  assert.equal(byClass(evidence, "run-request").length, 0);
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
  assert.equal(byClass(evidence, "run-request").length, 0);
});

test("a check nobody has run yet still carries its waiting review", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    // No qa_run, so no artifacts — the review is exactly what is waiting.
    rows: [activityRow({ run_id: null, outcome: "queued", artifacts: [] })],
    pending: [qaRequestRow({
      id: 4403,
      status: "pending",
      subject_key: "26134",
      subject_context: {
        ...qaRequestRow().subject_context, requirement_id: 26134,
      },
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  assert.ok(evidence, "the entry is drawn for a check with no run");
  const review = byClass(evidence, "run-request")[0];
  assert.equal(review.getAttribute("data-request-id"), "4403");
  // The item's history carries no capture at all, so suppressing the
  // request's own evidence would leave a verdict asked on nothing visible.
  assert.equal(byClass(review, "review-evidence").length, 1);
});

test("a review that names another run is not offered under this run", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    rows: [activityRow({ requirement_id: 26134 })],
    pending: [itemReviewRow({
      id: 4501,
      subject_context: {
        ...itemReviewRow().subject_context,
        subject: {
          ...itemReviewRow().subject_context.subject,
          deployment_run_id: "run-20260910-003",
        },
      },
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  assert.equal(byClass(evidence, "run-request").length, 0);
});

test("a request whose evidence is already on screen does not draw it twice", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    // The deployed revision's check IS the capture this request rests on.
    rows: [activityRow({
      artifacts: [artifact(1, 26134), artifact(2, 26134)],
      deployment_run_id: RUN_ID,
      execution_target_json: deployedTarget(),
    })],
    pending: [qaRequestRow({
      id: 4600,
      status: "pending",
      subject_key: "26134",
      subject_context: {
        ...qaRequestRow().subject_context,
        requirement_id: 26134,
        artifacts: [
          { artifact_id: 1, artifact_type: "screenshot", content_type: "image/png" },
          { artifact_id: 2, artifact_type: "screenshot", content_type: "image/png" },
        ],
        artifact_count: 2,
      },
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  const review = byClass(evidence, "run-request")[0];
  assert.equal(review.getAttribute("data-request-id"), "4600");
  // Proven already shown by artifact identity, so it is not repeated. Both
  // sit inside what the check's strip draws, so both are genuinely on screen.
  assert.equal(byClass(review, "review-evidence").length, 0);
  assert.equal(byClass(evidence, "review-shot").length, 2);
});

test("a request whose evidence sits behind +N more still draws it", async () => {
  const documentNode = new FakeDocument();
  const client = readingClient({
    // Eight captures, of which the check's strip draws six; this request
    // rests on the seventh, which nobody has seen until they click.
    rows: [activityRow({
      artifacts: [1, 2, 3, 4, 5, 6, 7, 8].map((id) => artifact(id, 26134)),
      deployment_run_id: RUN_ID,
      execution_target_json: deployedTarget(),
    })],
    pending: [qaRequestRow({
      id: 4601,
      status: "pending",
      subject_key: "26134",
      subject_context: {
        ...qaRequestRow().subject_context,
        requirement_id: 26134,
        artifacts: [
          { artifact_id: 7, artifact_type: "screenshot", content_type: "image/png" },
        ],
        artifact_count: 1,
      },
    })],
  });
  const { card } = await cardFor(documentNode, [member(1896, "BUZ-1896")], client);
  await settle();

  const evidence = byClass(memberEntry(card), "carried-item-evidence")[0];
  const review = byClass(evidence, "run-request")[0];
  assert.equal(review.getAttribute("data-request-id"), "4601");
  // Passed to the strip is not the same as drawn by it: six are on screen
  // and the rest are folded away, so this request keeps its own evidence.
  assert.equal(byClass(evidence, "review-more").length, 1);
  assert.equal(byClass(review, "review-evidence").length, 1);
});
