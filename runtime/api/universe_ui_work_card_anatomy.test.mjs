import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  resetBandDisclosureState,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_band_primitives.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  ownTextContent,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { workbenchClient } from "./universe_ui_workbench_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
    resetBandDisclosureState();
  });
  globalThis.fetch = () => response(200, {});
  resetBandDisclosureState();
}

async function mountAt(documentNode, hash) {
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: workbenchClient() });
  await settle();
  return { mounted, root };
}

test("a band is a native disclosure carrying its own count", async (t) => {
  stubFetch(t);
  const { mounted, root } = await mountAt(new FakeDocument(), "#/frontier?project=1");
  const bands = byClass(root, "work-band");
  assert.equal(bands.every((node) => node.tagName === "DETAILS"), true);
  assert.equal(bands.every((node) => node.children[0].tagName === "SUMMARY"), true);
  assert.deepEqual(
    bands.map((node) => node.attributes.get("data-fold")),
    ["band:waiting", "band:ready", "band:active", "band:release", "band:done"],
  );
  assert.equal(bands.every((node) => node.open), true);
  assert.equal(byClass(bands[0], "band-chevron").length, 1);
  assert.equal(byClass(bands[0], "work-band-rule").length, 1);
  // Counts live on the bands, never on the page heading.
  assert.deepEqual(
    byClass(root, "work-band-count").map(ownTextContent),
    ["1", "1", "0", "0", "1"],
  );
  assert.equal(byClass(root, "title")[0].textContent, "Frontier");
  mounted.unmount();
});

test("strategy cards carry badge, slug, age, claim and summary once", async (t) => {
  stubFetch(t);
  const { mounted, root } = await mountAt(new FakeDocument(), "#/strategy?project=1");
  // Standing direction and plans are separate bands; the archive keeps its
  // own, still reachable.
  assert.equal(
    byClass(byClass(root, "work-band-standing")[0], "strategy-doc-card").length, 1,
  );
  assert.equal(
    byClass(byClass(root, "work-band-plans")[0], "strategy-doc-card").length, 1,
  );
  assert.equal(
    byClass(byClass(root, "work-band-archived-docs")[0], "strategy-doc-card").length,
    1,
  );
  assert.equal(byClass(root, "strategy-doc-card").length, 3);
  assert.equal(byClass(root, "strategy-doc-age-dot").length, 3);
  assert.deepEqual(
    byClass(root, "strategy-doc-prefix").map(ownTextContent),
    ["YOK", "YOK", "YOK"],
  );
  // A steering seat and a Blitz are different holds and read differently.
  assert.deepEqual(
    byClass(root, "strategy-doc-claim-label").map((node) => node.textContent),
    ["STEERED", "Blitz"],
  );
  assert.deepEqual(
    byClass(root, "strategy-doc-state").map((node) => node.textContent),
    ["locked"],
  );
  assert.deepEqual(
    byClass(root, "strategy-doc-summary").map((node) => node.textContent),
    [
      "Build a calmer delivery system.",
      "Ship the next reliable slice.",
      "Superseded direction.",
    ],
  );
  const leafText = allNodes(root)
    .filter((node) => node.children.length === 0)
    .map((node) => node.textContent);
  assert.equal(leafText.filter(
    (text) => text === "Build a calmer delivery system.",
  ).length, 1, "authored summary renders exactly once");
  mounted.unmount();
});

test("a shipping card carries its release, stages and carried work", async (t) => {
  stubFetch(t);
  const { mounted, root } = await mountAt(new FakeDocument(), "#/shipping?project=1");
  assert.equal(byClass(root, "title")[0].textContent, "Shipping");
  // No count in the page title, and no band around the cards.
  assert.equal(byClass(root, "work-band").length, 0);
  assert.equal(byClass(root, "shipping-run-card").length, 2);
  assert.equal(byClass(root, "release-batch").length, 2);
  assert.equal(byClass(root, "delivery-stage-bar").length, 2);
  mounted.unmount();
});

test("a closed band remains closed across a complete rerender", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  const first = await mountAt(documentNode, "#/frontier?project=1");
  const waiting = byClass(first.root, "work-band")[0];
  const done = byClass(first.root, "work-band")[3];
  waiting.open = false;
  waiting.dispatchEvent(new Event("toggle"));
  done.open = false;
  done.dispatchEvent(new Event("toggle"));
  first.mounted.unmount();

  const second = await mountAt(documentNode, "#/frontier?project=1");
  const next = byClass(second.root, "work-band");
  assert.equal(next[0].open, false);
  assert.equal(next[1].open, true);
  assert.equal(next[3].open, false);
  second.mounted.unmount();
});
