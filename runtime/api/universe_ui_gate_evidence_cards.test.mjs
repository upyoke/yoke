// What a QA review SHOWS the person recording its verdict.
//
// A request backed by four screenshots and one backed by nothing used to
// reach the reviewer as the same row. These cases hold the difference, and
// hold the subject line that says which item, run and revision the evidence
// is evidence of.

import assert from "node:assert/strict";
import test from "node:test";

import {
  byClass,
  FakeDocument,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  artifactCaption,
  artifactEvidenceCard,
  artifactLabel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_evidence_artifact_view.js";
import {
  qaBareRequestRow,
  qaRequestRow,
  renderInbox,
  requestRow,
} from "./universe_ui_inbox_test_support.mjs";

const gateText = (main) => byClass(main, "gate-body")[0].textContent;

test("artifact captions lead with the authored capture label", () => {
  const artifact = {
    metadata: {
      label: "Approval actions and eligibility",
      route: "/inbox",
      step_index: 2,
      browser: "chromium",
    },
    artifact_handle: { backend: "s3", key: "private/raw-name.png" },
  };
  assert.equal(artifactLabel(artifact), "Approval actions and eligibility");
  assert.equal(
    artifactCaption(artifact),
    "Approval actions and eligibility · /inbox · step 2 · chromium",
  );
});

test("a QA review shows each artifact behind it, openable in place", async () => {
  const { main } = renderInbox("all", [qaRequestRow()]);
  await settle();

  // The stored title is the same fixed sentence for every QA review, so the
  // card names the case instead; a reviewer with three pending reviews could
  // otherwise not tell them apart.
  assert.equal(
    byClass(main, "inbox-row-title")[0].textContent,
    "Review marketing-pages-visual",
  );
  const body = gateText(main);
  assert.ok(body.includes("Evidence · 3 artifacts"), body);
  assert.ok(body.includes("Nav collapses at 680px"), body);
  assert.ok(body.includes("Every marketing page renders"), body);
  // Exactly what the evidence is evidence OF: a screenshot with no subject,
  // run and revision beside it is a picture of some build.
  assert.ok(body.includes("What was checked"), body);
  assert.ok(body.includes("YOK-1907"), body);
  assert.ok(body.includes("run 4120"), body);
  assert.ok(body.includes("9f21c4ab77e3"), body);
  // One card per artifact. Screenshot bytes load immediately so the evidence
  // itself, not a count or a View button, leads the decision.
  assert.equal(byClass(main, "qa-evidence").length, 3);
  assert.equal(byClass(main, "qa-evidence-preview").length, 2);
  assert.equal(byClass(main, "qa-evidence-full").length, 2);
  assert.equal(byClass(main, "gate-evidence-none").length, 0);
});

test("a gate loads screenshots and links each preview full-size", async () => {
  const { client, main } = renderInbox("all", [qaRequestRow()]);
  await settle();

  const card = byClass(main, "qa-evidence")[0];
  // The read is addressed at the requirement the gate names, not at an item
  // or session the gate card would have to invent.
  const read = client.requests.filter(
    (request) => request.function === "qa.artifact.read",
  );
  assert.deepEqual(read.slice(0, 2).map((request) => request.target), [
    { kind: "qa_requirement", qa_requirement_id: 21583 },
    { kind: "qa_requirement", qa_requirement_id: 21583 },
  ]);
  assert.deepEqual(read.slice(0, 2).map((request) => request.payload), [
    { artifact_id: 1 }, { artifact_id: 2 },
  ]);

  const full = byClass(card, "qa-evidence-full")[0];
  assert.ok(full, "an image artifact opens at full size");
  assert.equal(full.target, "_blank");
  assert.ok(full.href.startsWith("data:image/png;base64,"), full.href);
  assert.equal(
    full.getAttribute("aria-label"), "Open full image: screenshot",
  );
  const preview = byClass(card, "qa-evidence-preview")[0];
  assert.equal(preview.href, undefined);
  assert.equal(preview.alt, "screenshot");
});

test("a gate artifact whose bytes are elsewhere says where, not nothing", async () => {
  const { main } = renderInbox("all", [qaRequestRow()]);
  await settle();

  // The third fixture artifact reads back as living on its capture machine.
  const card = byClass(main, "qa-evidence")[2];
  byClass(card, "qa-evidence-action")[0].dispatchEvent(new Event("click"));
  await settle();

  assert.equal(
    byClass(card, "qa-evidence-action")[0].textContent, "on studio-mini",
  );
  assert.ok(
    card.textContent.includes("the evidence bytes are not present"),
    card.textContent,
  );
});

test("a QA review with no artifacts refuses instead of looking the same", async () => {
  const { main } = renderInbox("all", [qaBareRequestRow()]);
  await settle();

  assert.equal(byClass(main, "qa-evidence").length, 0);
  const refusal = byClass(main, "gate-evidence-none")[0];
  assert.ok(refusal, "a run with no artifacts must say so");
  assert.ok(
    refusal.textContent.includes("a verdict on nothing"),
    refusal.textContent,
  );
});

test("a deployment QA review claims nothing about what has shipped", async () => {
  // The real shape this guards: a run still waiting at its approval stage,
  // whose materialized plan requirements are already declared post_deploy.
  // `qa_phase` says how the check was DECLARED, so reading it as proof the
  // release completed tells the reviewer something untrue.
  const facts = qaRequestRow().subject_context;
  const { main } = renderInbox("all", [qaRequestRow({
    subject_context: {
      ...facts,
      subject: {
        kind: "deployment_run",
        item_id: null,
        item_ref: null,
        item_title: null,
        deployment_run_id: "run-20260909-027",
        target_environment: "prod",
        qa_phase: "post_deploy",
      },
    },
  })]);
  await settle();

  const body = gateText(main);
  assert.ok(body.includes("declared post_deploy against run-20260909-027"), body);
  assert.ok(body.includes("can gate that run's completion"), body);
  assert.ok(body.includes("cannot undo code the run has already deployed"), body);
  assert.ok(!body.includes("completed, so"), body);
  assert.ok(!body.includes("ran after the release"), body);
});

test("an item completion approval says it deploys nothing", async () => {
  // Approving an item's last transition is a record of state. Reading it as
  // permission to ship is the confusion the sentence exists to remove.
  const { main } = renderInbox("all", [requestRow({
    subject_context: { ...requestRow().subject_context, to_stage: "done" },
  })]);
  await settle();

  const body = gateText(main);
  assert.ok(
    body.includes("This records the item's state only — it deploys nothing "
      + "and releases nothing to any environment."),
    body,
  );
});

test("a lifecycle approval opens its attached screenshot immediately", async () => {
  const base = requestRow();
  const { main } = renderInbox("all", [requestRow({
    subject_context: {
      ...base.subject_context,
      evidence: {
        state: "attached",
        screenshots: [{
          artifact_id: 1,
          artifact_type: "screenshot",
          content_type: "image/png",
          requirement_id: 21583,
        }],
      },
    },
  })]);
  await settle();

  assert.equal(byClass(main, "qa-evidence-preview").length, 1);
  assert.equal(byClass(main, "qa-evidence-full").length, 1);
});

test("a stalled screenshot read fails loudly and remains retryable", async () => {
  const documentNode = new FakeDocument();
  const card = artifactEvidenceCard({
    document: documentNode,
    evidenceReadTimeoutMs: 1,
    client: { call: () => new Promise(() => {}) },
  }, {
    artifact_id: 81,
    artifact_type: "screenshot",
    content_type: "image/png",
    requirement_id: 92,
  });
  await new Promise((resolve) => setTimeout(resolve, 5));

  assert.match(card.textContent, /timed out/i);
  assert.equal(byClass(card, "qa-evidence-action")[0].textContent, "retry →");
  assert.equal(byClass(card, "qa-evidence-action")[0].disabled, false);
});
