// Network counts for evidence-strip screenshot reads: hidden overflow
// must not fetch, a second figure of the same artifact shares the
// in-flight call, leaving the view aborts, and a timed-out fetch is
// cancelled when the HTTP client is the one in use.

import assert from "node:assert/strict";
import test from "node:test";

import {
  byClass,
  FakeDocument,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { createHttpFunctionClient } from "../../packages/yoke-core/src/yoke_core/ui/static/contract.js";
import { replaceViewAbort } from "../../packages/yoke-core/src/yoke_core/ui/static/mount-options.js";
import {
  EVIDENCE_SHOWN,
  evidenceStrip,
} from "../../packages/yoke-core/src/yoke_core/ui/static/review_evidence_strip.js";

function shot(id) {
  return {
    artifact_id: id,
    artifact_type: "screenshot",
    content_type: "image/png",
    requirement_id: 92,
  };
}

function countingClient(hang = false) {
  const calls = [];
  const aborts = [];
  return {
    calls,
    aborts,
    call(request, init) {
      calls.push(request);
      init?.signal?.addEventListener("abort", () => {
        aborts.push(request.payload.artifact_id);
      });
      if (hang) return new Promise(() => {});
      return Promise.resolve({
        status: 200,
        envelope: {
          success: true,
          result: {
            disposition: "ready",
            content_type: "image/png",
            content_base64: "xx",
          },
        },
      });
    },
  };
}

function shots(count, start = 1) {
  return Array.from({ length: count }, (_, index) => shot(start + index));
}

test("collapsed overflow does not read hidden screenshots", async () => {
  const documentNode = new FakeDocument();
  const client = countingClient();
  const strip = evidenceStrip(
    { document: documentNode, client },
    shots(EVIDENCE_SHOWN + 2),
  );
  await settle();

  assert.equal(client.calls.length, EVIDENCE_SHOWN);
  assert.equal(byClass(strip, "review-shot").length, EVIDENCE_SHOWN);
  assert.equal(byClass(strip, "review-evidence-rest")[0].children.length, 0);
});

test("expanding overflow reads the remaining screenshots", async () => {
  const documentNode = new FakeDocument();
  const client = countingClient();
  const strip = evidenceStrip(
    { document: documentNode, client },
    shots(EVIDENCE_SHOWN + 2, 20),
  );
  await settle();
  byClass(strip, "review-more")[0].dispatchEvent(new Event("click"));
  await settle();

  assert.equal(client.calls.length, EVIDENCE_SHOWN + 2);
  assert.equal(
    byClass(strip, "review-evidence-rest")[0].children.length, 2,
  );
});

test("two figures of the same artifact share one in-flight read", async () => {
  const documentNode = new FakeDocument();
  const client = countingClient();
  const strip = evidenceStrip(
    { document: documentNode, client },
    [shot(81), shot(81)],
  );
  await settle();

  assert.equal(byClass(strip, "review-shot").length, 2);
  assert.equal(client.calls.length, 1);
});

test("two strips on one view share one in-flight read", async () => {
  const documentNode = new FakeDocument();
  const client = countingClient(true);
  const context = { document: documentNode, client };
  replaceViewAbort(context);
  const first = evidenceStrip(context, [shot(81)]);
  const second = evidenceStrip(context, [shot(81)]);
  await settle();

  assert.equal(byClass(first, "review-shot").length, 1);
  assert.equal(byClass(second, "review-shot").length, 1);
  assert.equal(client.calls.length, 1);
  assert.equal(context.artifactReads.size, 1);

  context.abortView();
  await settle();
  assert.equal(client.aborts.length, 1);
});

test("a replacement view fetches the same artifact instead of the aborted read", async () => {
  const documentNode = new FakeDocument();
  const client = countingClient(true);
  const context = { document: documentNode, client };
  replaceViewAbort(context);
  const first = evidenceStrip(context, [shot(81)]);
  await settle();
  const previousReads = context.artifactReads;
  assert.equal(client.calls.length, 1);

  replaceViewAbort(context);
  const next = evidenceStrip(context, [shot(81)]);
  await settle();

  assert.notEqual(context.artifactReads, previousReads);
  assert.equal(previousReads.size, 0);
  assert.equal(context.artifactReads.size, 1);
  assert.equal(client.calls.length, 2);
  assert.equal(
    byClass(next, "review-shot")[0].classList.contains("is-unavailable"), false,
  );
  assert.equal(
    byClass(first, "review-shot")[0].classList.contains("is-unavailable"), true,
  );
});

test("leaving the view aborts through the view disposal signal", async () => {
  const documentNode = new FakeDocument();
  const client = countingClient(true);
  const context = { document: documentNode, client };
  replaceViewAbort(context);
  evidenceStrip(context, [shot(55)]);
  await settle();
  assert.equal(client.calls.length, 1);
  assert.equal(client.aborts.length, 0);

  context.abortView();
  await settle();
  assert.equal(client.aborts.length, 1);
});

test("a timed-out screenshot read aborts the request when the client supports it", async () => {
  const documentNode = new FakeDocument();
  const client = countingClient(true);
  const strip = evidenceStrip({
    document: documentNode,
    client,
    evidenceReadTimeoutMs: 1,
  }, [shot(81)]);
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.equal(client.aborts.length, 1);
  assert.match(
    byClass(strip, "review-shot-state")[0].textContent, /timed out/i,
  );
});

test("a strip read through the HTTP client aborts fetch on view dispose", async () => {
  const documentNode = new FakeDocument();
  let fetchInit;
  const client = createHttpFunctionClient({
    fetch: (_url, options) => {
      fetchInit = options;
      return new Promise((_, reject) => {
        options.signal.addEventListener("abort", () => {
          const error = new Error("The operation was aborted");
          error.name = "AbortError";
          reject(error);
        });
      });
    },
  });
  const context = { document: documentNode, client };
  replaceViewAbort(context);
  evidenceStrip(context, [shot(81)]);
  await settle();
  assert.equal(typeof fetchInit.signal.addEventListener, "function");
  assert.equal(fetchInit.signal.aborted, false);

  context.abortView();
  await settle();
  assert.equal(fetchInit.signal.aborted, true);
});
