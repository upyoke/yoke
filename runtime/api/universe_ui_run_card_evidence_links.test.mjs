// What a person can click on a deployment run card, and what each click
// opens.
//
// The card used to be one card-wide anchor wrapped around everything
// readable: hovering blank space lit the whole card, the text under the
// cursor could not be selected, and a click aimed at a screenshot opened the
// run. These cases hold the shape that replaced it — a run name that is the
// link to the run, and evidence whose picture and caption each open that
// one artifact.

import assert from "node:assert/strict";
import test from "node:test";

import {
  byClass,
  FakeDocument,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  overviewRunCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_overview_cards.js";
import { evidenceStrip } from "../../packages/yoke-core/src/yoke_core/ui/static/review_evidence_strip.js";
import { closeLightbox } from "../../packages/yoke-core/src/yoke_core/ui/static/review_lightbox.js";

const PNG = "iVBORw0KGgo=";

function screenshotArtifact(overrides = {}) {
  return {
    id: 77,
    artifact_type: "screenshot",
    content_type: "image/png",
    requirement_id: 21583,
    metadata: {
      label: "sample-qa-evidence-inbox",
      route: "/orgs/upyoke#/inbox?project=1",
      step_index: 21,
      browser: "chromium",
    },
    ...overrides,
  };
}

function readingContext(documentNode, artifacts = []) {
  return {
    document: documentNode,
    capabilities: {},
    projects: () => [{ id: 1, slug: "yoke", name: "Yoke" }],
    client: {
      call: async () => ({
        status: 200,
        envelope: {
          success: true,
          result: {
            disposition: "ready",
            content_type: "image/png",
            content_base64: PNG,
          },
        },
      }),
    },
    artifacts,
  };
}

function runRow() {
  return {
    id: "run-20260910-006",
    project: "yoke",
    status: "executing",
    flow: "yoke-hosted-stage-typed-target",
    target_environment: "stage",
    created_at: "2026-09-10T10:00:00Z",
    stages: [{ name: "sample-review", state: "complete" }],
    gates: [],
  };
}

function runCard(documentNode, artifacts) {
  const context = readingContext(documentNode, artifacts);
  return overviewRunCard(context, runRow(), ["1"], {
    facts: {
      evidence: new Map([["run-20260910-006", { checks: [], artifacts }]]),
      flowNames: new Map([["yoke-hosted-stage-typed-target", "Stage"]]),
      failed: null,
    },
  });
}

test("the run name is the card's link, and the card itself is not one", () => {
  const documentNode = new FakeDocument();
  const card = runCard(documentNode, []);

  assert.equal(card.tagName, "DIV");
  assert.equal(byClass(card, "overview-run-card-link").length, 0);
  const runName = byClass(card, "overview-run-id")[0];
  assert.equal(runName.tagName, "A");
  assert.equal(runName.textContent, "run-20260910-006");
  assert.equal(runName.href, "#/deployments/runs/run-20260910-006?project=1");
  // Everything else the card reads out is text, so there is nothing between
  // the reader and selecting it.
  assert.deepEqual(
    byClass(card, "overview-run-flow").map((node) => node.tagName), ["STRONG"],
  );
  assert.equal(byClass(card, "overview-run-environment")[0].tagName, "SPAN");
});

test("a run card's screenshot opens its own evidence, not the run", async () => {
  const documentNode = new FakeDocument();
  const card = runCard(documentNode, [screenshotArtifact()]);
  await settle();

  const shot = byClass(card, "review-shot")[0];
  assert.ok(shot.classList.contains("is-ready"), shot.className);
  const picture = byClass(shot, "review-shot-open")[0];
  assert.ok(picture.href.startsWith("data:image/png;base64,"), picture.href);
  assert.notEqual(picture.href, byClass(card, "overview-run-id")[0].href);

  picture.dispatchEvent(new Event("click"));
  const lightbox = byClass(documentNode.body, "review-lightbox")[0];
  assert.ok(lightbox, "the screenshot opens in the artifact viewer");
  assert.equal(closeLightbox(documentNode), true);
});

test("a caption is the step it was taken at, hyperlinked to that evidence", async () => {
  const documentNode = new FakeDocument();
  const strip = evidenceStrip(
    readingContext(documentNode), [screenshotArtifact()], { compact: true },
  );
  await settle();

  const caption = byClass(strip, "review-shot-caption")[0];
  // Only the step, not the four-clause capture record the caption used to
  // spell out under every thumbnail.
  assert.equal(caption.textContent, "step 21");
  const step = byClass(caption, "review-shot-step")[0];
  assert.equal(step.tagName, "A");
  assert.ok(step.href.startsWith("data:image/png;base64,"), step.href);
  // The capture's own record is preserved beside the picture rather than
  // printed under it.
  assert.equal(
    byClass(strip, "review-shot")[0].title,
    "sample-qa-evidence-inbox · /orgs/upyoke#/inbox?project=1 · step 21 · chromium",
  );

  step.dispatchEvent(new Event("click"));
  assert.ok(byClass(documentNode.body, "review-lightbox")[0]);
  assert.equal(closeLightbox(documentNode), true);
});

test("a capture with no step keeps its own name for a caption", async () => {
  const documentNode = new FakeDocument();
  const strip = evidenceStrip(
    readingContext(documentNode),
    [screenshotArtifact({ metadata: { label: "Desktop approval request" } })],
    {},
  );
  await settle();

  assert.equal(
    byClass(strip, "review-shot-caption")[0].textContent,
    "Desktop approval request",
  );
});
