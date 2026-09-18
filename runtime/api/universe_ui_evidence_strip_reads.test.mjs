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

test("leaving the view aborts an in-flight screenshot read", async () => {
  const documentNode = new FakeDocument();
  const client = countingClient(true);
  let mounted = true;
  evidenceStrip(
    { document: documentNode, client, isMounted: () => mounted },
    [shot(55)],
  );
  await settle();
  assert.equal(client.calls.length, 1);
  assert.equal(client.aborts.length, 0);

  mounted = false;
  await new Promise((resolve) => setTimeout(resolve, 50));
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

test("the HTTP client forwards abort to fetch", async () => {
  const controller = new AbortController();
  let init;
  const client = createHttpFunctionClient({
    fetch: (_url, options) => {
      init = options;
      return new Promise((_, reject) => {
        options.signal.addEventListener("abort", () => {
          const error = new Error("The operation was aborted");
          error.name = "AbortError";
          reject(error);
        });
      });
    },
  });
  const pending = client.call(
    { function: "qa.artifact.read", payload: { artifact_id: 81 } },
    { signal: controller.signal },
  );
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(init.signal.aborted, true);
});
