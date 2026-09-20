// What the Frontier screen spends before it can paint. The bands are one
// reading of one roster and paint together, so every read they need belongs
// in flight at once — and the open session roster, which two of them want,
// belongs read once.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { workbenchClient } from "./universe_ui_workbench_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function mountFrontier(client) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/frontier?project=1";
  const root = documentNode.createElement("div");
  mountUniverseApp(root, { client });
  await settle();
  return root;
}

const named = (client, functionId) => client.requests.filter(
  (request) => request.function === functionId,
);

test("the screen's own roster read also ranks its steering tints", async (t) => {
  stubFetch(t);
  const client = workbenchClient();
  await mountFrontier(client);

  // Two open-roster reads reach the server on this route, and only two: the
  // app-wide tint refresh every route starts at mount, and the one this
  // screen needs to tell which work is in flight. The screen ranks its tints
  // from the rows it already holds rather than asking a third time.
  const open = named(client, "sessions.list").filter((request) => (
    request.payload?.per_project === true && request.payload?.open === true
  ));
  assert.equal(open.length, 2);
});

test("the item reads do not wait for the release roster", async (t) => {
  stubFetch(t);
  const base = workbenchClient();
  let releaseReadyResolve;
  const releaseReady = new Promise((resolve) => { releaseReadyResolve = resolve; });
  const seenBeforeRunsAnswered = [];
  const client = {
    requests: base.requests,
    async call(request) {
      if (request.function === "deployment_runs.list") {
        await releaseReady;
        return base.call(request);
      }
      seenBeforeRunsAnswered.push(request.function);
      return base.call(request);
    },
  };

  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/frontier?project=1";
  const root = documentNode.createElement("div");
  mountUniverseApp(root, { client });
  await settle();

  // The run roster answers a different question, and nothing in the item
  // reads depends on it, so they are already out while it is still pending.
  assert.ok(seenBeforeRunsAnswered.includes("items.overview.list"));
  assert.ok(seenBeforeRunsAnswered.includes("frontier.list"));

  releaseReadyResolve();
  await settle();
  // And the delivery the run roster carries still reaches the cards.
  assert.ok(named(client, "deployment_runs.list").length >= 1);
  assert.ok(root.textContent.includes("Release"));
});
