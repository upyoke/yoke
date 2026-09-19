// The three states one evidence thumbnail can be in, and the single box that
// carries the two of them that have words.
//
// A tile reads its own bytes after it is already on screen, so "settled" is
// not the only thing it has to draw. These cases hold the unsettled window —
// long enough to photograph wherever a surface opens several tiles at once —
// and hold the handover from it to each settled end, so a reader always sees
// a framed slot that says which of the three it is looking at.

import assert from "node:assert/strict";
import test from "node:test";

import {
  allNodes,
  byClass,
  FakeDocument,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { evidenceStrip } from "../../packages/yoke-core/src/yoke_core/ui/static/review_evidence_strip.js";

function screenshotStrip(documentNode, context) {
  return evidenceStrip(
    { document: documentNode, ...context },
    [{
      artifact_id: 81,
      artifact_type: "screenshot",
      content_type: "image/png",
      metadata: { step_index: 4 },
    }],
    { requirementId: 92 },
  );
}

// A read that never answers, run down to its own timeout.
function stalledStrip(documentNode) {
  return screenshotStrip(documentNode, {
    evidenceReadTimeoutMs: 1,
    client: { call: () => new Promise(() => {}) },
  });
}

const afterTimeout = () => new Promise((resolve) => setTimeout(resolve, 5));

// The window between mount and settle is a state of its own. A strip reads
// one artifact per tile, so on a surface carrying several of them at once
// that window is long enough to photograph — and it used to photograph as
// nothing, because the picture carries the slot's frame and stays hidden
// until it has a source.
test("a thumbnail still being read says so instead of showing blank space", async () => {
  const documentNode = new FakeDocument();
  let release;
  const strip = screenshotStrip(documentNode, {
    client: { call: () => new Promise((resolve) => { release = resolve; }) },
  });
  await settle();

  const shot = byClass(strip, "review-shot")[0];
  assert.ok(shot.classList.contains("is-pending"), shot.className);
  assert.equal(
    byClass(shot, "review-shot-state")[0].textContent, "Loading evidence…",
  );

  release({
    status: 200,
    envelope: { success: true, result: {
      artifact_id: 81, disposition: "ready", content_type: "image/png",
      content_base64: "iVBORw0KGgo=",
    } },
  });
  await settle();

  // Settled: the state box is gone rather than sitting behind the picture.
  assert.equal(shot.classList.contains("is-pending"), false);
  assert.ok(shot.classList.contains("is-ready"), shot.className);
  assert.equal(byClass(shot, "review-shot-state").length, 0);
  assert.match(byClass(shot, "review-shot-image")[0].src, /^data:image\/png;base64,/);
});

test("a thumbnail whose read times out says so in place", async () => {
  const documentNode = new FakeDocument();
  const strip = stalledStrip(documentNode);
  await afterTimeout();

  const shot = byClass(strip, "review-shot")[0];
  assert.ok(shot.classList.contains("is-unavailable"), shot.className);
  assert.match(
    allNodes(shot).map((node) => node.textContent).join(" "), /timed out/i,
  );
});

// One box, two states with words: the reason a read failed lands in the same
// node the pending label used, so a tile never stacks both and never loses
// its frame on the way between them.
test("a failed read replaces the loading label in the same box", async () => {
  const documentNode = new FakeDocument();
  const strip = stalledStrip(documentNode);
  await afterTimeout();

  const shot = byClass(strip, "review-shot")[0];
  const states = byClass(shot, "review-shot-state");
  assert.equal(states.length, 1);
  assert.equal(shot.classList.contains("is-pending"), false);
  assert.match(states[0].textContent, /timed out/i);
});
