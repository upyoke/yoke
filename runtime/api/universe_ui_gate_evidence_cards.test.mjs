// What a QA review SHOWS the person recording its verdict, and how every
// request draws the evidence it rests on.
//
// A request backed by four screenshots and one backed by nothing used to
// reach the reviewer as the same row. These cases hold the difference, hold
// the facts that say which item, run and revision the evidence is evidence
// of, and hold the strip itself: pictures first, text as a chip, and a plain
// word for bytes that are not here.

import assert from "node:assert/strict";
import test from "node:test";

import {
  allNodes,
  byClass,
  FakeDocument,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  artifactCaption,
  artifactEvidenceCard,
  artifactLabel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_evidence_artifact_view.js";
import { evidenceStrip } from "../../packages/yoke-core/src/yoke_core/ui/static/review_evidence_strip.js";
import { closeLightbox } from "../../packages/yoke-core/src/yoke_core/ui/static/review_lightbox.js";
import {
  qaBareRequestRow,
  qaRequestRow,
  renderInbox,
  requestRow,
} from "./universe_ui_inbox_test_support.mjs";

const cardText = (main) => byClass(main, "review-card")[0].textContent;

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

test("a QA review shows what was checked, what the agent said, and each artifact", async () => {
  const { main } = renderInbox("all", [qaRequestRow()]);
  await settle();

  // The stored title is the same fixed sentence for every QA review, so the
  // card names the case instead; a reviewer with three pending reviews could
  // otherwise not tell them apart.
  assert.ok(byClass(main, "review-kind")[0].textContent.startsWith("QA review"));
  assert.equal(
    byClass(main, "review-title")[0].textContent,
    "Review marketing-pages-visual",
  );
  const facts = byClass(main, "review-qa")[0];
  assert.deepEqual(
    facts.children.filter((node) => node.tagName === "DT").map((node) => node.textContent),
    ["Checked", "Expected", "Agent said"],
  );
  const body = cardText(main);
  assert.ok(body.includes("YOK-1907 · Approval evidence review"), body);
  assert.ok(body.includes("run 4120 · verification · revision 9f21c4ab77e3"), body);
  assert.ok(body.includes("Every marketing page renders at 680px and 1024px."), body);
  assert.ok(body.includes("Nav collapses at 680px"), body);
  assert.ok(body.includes("Is this acceptable?"), body);
  // Two screenshots as thumbnails, one log as a text chip.
  assert.equal(byClass(main, "review-shot").length, 2);
  assert.equal(byClass(main, "review-text-chip").length, 1);
  assert.deepEqual(
    byClass(main, "review-action").map((node) => node.textContent),
    ["Waive", "Reject", "Approve"],
  );
});

test("a QA review loads its screenshots at once, addressed at the requirement", async () => {
  const { client, main } = renderInbox("all", [qaRequestRow()]);
  await settle();

  // The read is addressed at the requirement the request names, not at an
  // item or session the card would have to invent.
  const read = client.requests.filter(
    (request) => request.function === "qa.artifact.read",
  );
  assert.deepEqual(read.map((request) => request.target), [
    { kind: "qa_requirement", qa_requirement_id: 21583 },
    { kind: "qa_requirement", qa_requirement_id: 21583 },
  ]);
  assert.deepEqual(read.map((request) => request.payload), [
    { artifact_id: 1 }, { artifact_id: 2 },
  ]);
  const shot = byClass(main, "review-shot")[0];
  assert.ok(shot.classList.contains("is-ready"), shot.className);
  const image = byClass(shot, "review-shot-image")[0];
  assert.ok(image.src.startsWith("data:image/png;base64,"), image.src);
  assert.equal(image.alt, "screenshot");
  assert.equal(shot.getAttribute("aria-label"), "Open full size: screenshot");
});

test("a thumbnail opens the picture in place, and Esc closes it", async () => {
  const documentNode = new FakeDocument();
  const { main } = renderInbox("all", [qaRequestRow()]);
  await settle();
  // The inbox fixture renders into its own document; the lightbox lives on
  // whichever document the shot belongs to.
  const shot = byClass(main, "review-shot")[0];
  const owner = shot.ownerDocument;
  shot.dispatchEvent(new Event("click"));

  const lightbox = byClass(owner.body, "review-lightbox")[0];
  assert.ok(lightbox, "the picture opens in a lightbox");
  assert.equal(lightbox.getAttribute("aria-modal"), "true");
  assert.ok(byClass(lightbox, "review-lightbox-image")[0].src.startsWith("data:image/png"));
  assert.equal(byClass(lightbox, "review-lightbox-open")[0].target, "_blank");
  owner.defaultView.dispatchEvent(Object.assign(new Event("keydown"), { key: "Escape" }));
  assert.equal(byClass(owner.body, "review-lightbox").length, 0);
  assert.equal(closeLightbox(documentNode), false);
});

test("a text artifact is one chip that opens the stored text", async () => {
  const documentNode = new FakeDocument();
  const requests = [];
  const strip = evidenceStrip({
    document: documentNode,
    client: {
      async call(request) {
        requests.push(request);
        return {
          status: 200,
          envelope: { success: true, result: {
            artifact_id: 5, disposition: "ready", content_type: "text/plain",
            content_base64: Buffer.from("248 passed in 3.1s").toString("base64"),
          } },
        };
      },
    },
  }, [{ artifact_id: 5, artifact_type: "command_output", content_type: "text/plain" }], {
    requirementId: 40,
  });
  await settle();

  const chip = byClass(strip, "review-text-chip")[0];
  assert.equal(byClass(chip, "review-text-chip-kind")[0].textContent, "command output");
  // Nothing is read until asked: a log is bytes the reviewer may never need.
  assert.equal(requests.length, 0);
  chip.dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(requests[0].target, { kind: "qa_requirement", qa_requirement_id: 40 });
  const text = byClass(documentNode.body, "review-lightbox-text")[0];
  assert.equal(text.textContent, "248 passed in 3.1s");
});

test("an artifact whose bytes are elsewhere says where, not nothing", async () => {
  const { main } = renderInbox("all", [qaRequestRow()]);
  await settle();

  // The third fixture artifact reads back as living on its capture machine.
  const chip = byClass(main, "review-text-chip")[0];
  chip.dispatchEvent(new Event("click"));
  await settle();

  assert.ok(chip.classList.contains("is-unavailable"), chip.className);
  assert.equal(byClass(chip, "review-text-chip-kind")[0].textContent, "On studio-mini");
});

test("a QA review with no artifacts refuses instead of looking the same", async () => {
  const { main } = renderInbox("all", [qaBareRequestRow()]);
  await settle();

  assert.equal(byClass(main, "review-shot").length, 0);
  const refusal = byClass(main, "review-evidence-none")[0];
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

  const body = cardText(main);
  assert.ok(body.includes("run-20260909-027 · released to prod"), body);
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

  assert.equal(
    byClass(main, "review-effect")[0].textContent,
    "Moves the item to done. Deploys nothing.",
  );
  const body = cardText(main);
  assert.ok(
    body.includes("This records the item's state only — it deploys nothing "
      + "and releases nothing to any environment."),
    body,
  );
});

test("a work approval shows its attached screenshot and says nothing when it has none", async () => {
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
  }), requestRow({ id: 8 })]);
  await settle();

  const cards = byClass(main, "review-card");
  assert.equal(byClass(cards[0], "review-shot").length, 1);
  assert.ok(byClass(cards[0], "review-shot")[0].classList.contains("is-ready"));
  // No screenshots on a work approval is not a defect, so no warning.
  assert.equal(byClass(cards[1], "review-shot").length, 0);
  assert.equal(byClass(cards[1], "review-evidence-none").length, 0);
});

test("stale screenshot evidence is flagged beside the pictures", async () => {
  const base = requestRow();
  const { main } = renderInbox("all", [requestRow({
    subject_context: {
      ...base.subject_context,
      evidence: {
        state: "stale",
        screenshots: [{
          artifact_id: 1, artifact_type: "screenshot", content_type: "image/png",
          requirement_id: 21583,
        }],
      },
    },
  })]);
  await settle();
  assert.equal(
    byClass(main, "review-evidence-note")[0].textContent,
    "These screenshots cover an older revision than this decision.",
  );
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

test("a thumbnail whose read times out says so in place", async () => {
  const documentNode = new FakeDocument();
  const strip = evidenceStrip({
    document: documentNode,
    evidenceReadTimeoutMs: 1,
    client: { call: () => new Promise(() => {}) },
  }, [{ artifact_id: 81, artifact_type: "screenshot", content_type: "image/png" }], {
    requirementId: 92,
  });
  await new Promise((resolve) => setTimeout(resolve, 5));
  const shot = byClass(strip, "review-shot")[0];
  assert.ok(shot.classList.contains("is-unavailable"), shot.className);
  assert.match(
    allNodes(shot).map((node) => node.textContent).join(" "), /timed out/i,
  );
});
