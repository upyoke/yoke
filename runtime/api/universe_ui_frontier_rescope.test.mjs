import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  multiProjectWorkbenchClient,
} from "./universe_ui_workbench_test_support.mjs";

const activeRefs = (root) => byClass(
  byClass(root, "work-band-active")[0], "work-item-card-ref",
).map((node) => node.textContent);
const docSlugs = (root) => byClass(root, "strategy-doc-slug")
  .map((node) => node.textContent);
const callCount = (client, functionId) => client.requests.filter(
  (request) => request.function === functionId,
).length;
// A genuine scope change persists the new remembered selection — a
// deliberate write, not a content re-read. Held-scope repaint asserts stay
// about the page's OWN data, so the persistence write is excluded here.
const contentRequestCount = (client) => client.requests.filter(
  (request) => request.function !== "ui_preferences.screen_selection.set"
    && request.function !== "ui_preferences.screen_selection.list",
).length;

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function navigate(windowNode, hash) {
  windowNode.location.hash = hash;
  windowNode.dispatchEvent(new Event("hashchange"));
  await settle();
}

async function mountAt(documentNode, hash, client) {
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { root, mounted };
}

test("a project change repaints Frontier from held data with zero reads", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  const client = multiProjectWorkbenchClient();
  const { root, mounted } = await mountAt(
    documentNode, "#/frontier?project=1", client,
  );

  const before = contentRequestCount(client);
  assert.equal(callCount(client, "overview.activation.get"), 1);
  assert.equal(callCount(client, "items.overview.list"), 1);
  assert.equal(callCount(client, "deployment_runs.list"), 2);
  assert.deepEqual(activeRefs(root), ["YOK-9"]);

  const scopeBar = byClass(root, "scope-bar")[0];
  const pageHead = byClass(root, "page-head")[0];
  const waiting = byClass(root, "work-band-waiting")[0];

  await navigate(windowNode, "#/frontier?project=2");
  assert.equal(contentRequestCount(client), before);
  assert.deepEqual(activeRefs(root), ["BET-20"]);
  assert.equal(byClass(root, "scope-bar")[0], scopeBar);
  assert.equal(byClass(root, "page-head")[0], pageHead);
  assert.equal(byClass(root, "work-band-waiting")[0], waiting);

  await navigate(windowNode, "#/frontier?project=all");
  assert.equal(contentRequestCount(client), before);
  assert.deepEqual(activeRefs(root).sort(), ["BET-20", "YOK-9"]);
  mounted.unmount();
});

test("prefix chips repaint the held scope in place", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  const client = multiProjectWorkbenchClient();
  const { root, mounted } = await mountAt(
    documentNode, "#/frontier?project=1", client,
  );
  const before = contentRequestCount(client);
  const chip = (label) => byClass(root, "scope-chip")
    .find((node) => node.textContent === label);
  const chipState = () => byClass(root, "scope-chip").map(
    (node) => [node.textContent, node.classList.contains("on")],
  );

  // Adding the only other project covers this universe's whole roster,
  // which is the All scope — the page repaints to it from held data.
  chip("BET").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(contentRequestCount(client), before);
  assert.deepEqual(activeRefs(root).sort(), ["BET-20", "YOK-9"]);
  assert.deepEqual(chipState(), [["All", true], ["YOK", false], ["BET", false]]);
  assert.equal(documentNode.defaultView.location.hash, "#/frontier?project=all");

  chip("YOK").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(contentRequestCount(client), before);
  assert.deepEqual(activeRefs(root), ["YOK-9"]);
  assert.equal(documentNode.defaultView.location.hash, "#/frontier?project=1");
  mounted.unmount();
});

test("Strategy reads only the projects in scope, and rereads on a change", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  const client = multiProjectWorkbenchClient();
  const { root, mounted } = await mountAt(
    documentNode, "#/strategy?project=1", client,
  );
  // One read per project in scope rather than one per project in the
  // universe: a corpus is per-project, so a narrowed scope is a smaller read
  // rather than a filter applied to a larger one.
  assert.equal(callCount(client, "strategy.surface.list"), 1);
  assert.deepEqual(docSlugs(root), ["MISSION"]);

  await navigate(windowNode, "#/strategy?project=2");
  assert.equal(callCount(client, "strategy.surface.list"), 2);
  assert.deepEqual(docSlugs(root), ["BETA-PLAN"]);

  await navigate(windowNode, "#/strategy?project=all");
  assert.deepEqual(docSlugs(root).sort(), ["BETA-PLAN", "MISSION"]);
  mounted.unmount();
});

test("a failed project document read does not poison another scope", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  const client = multiProjectWorkbenchClient({ failProject: "2" });
  const { root, mounted } = await mountAt(
    documentNode, "#/strategy?project=1", client,
  );

  assert.equal(byClass(root, "work-band-error").length, 0);
  // Every band of the failed scope says the read failed, rather than one of
  // them rendering an empty corpus as if that were the answer.
  await navigate(windowNode, "#/strategy?project=2");
  assert.equal(byClass(root, "work-band-error").length, 3);
  await navigate(windowNode, "#/strategy?project=1");
  assert.equal(byClass(root, "work-band-error").length, 0);
  assert.deepEqual(docSlugs(root), ["MISSION"]);
  mounted.unmount();
});

// A band that overflows offers one "See more..." card, and that card encodes
// the page's CURRENT scope into the Items route. A scope covering the whole
// roster has to reach it as All: anything else writes a second form of the
// same scope into another screen's remembered selection.
function overflowingDoneClient() {
  const base = multiProjectWorkbenchClient();
  const done = Array.from({ length: 9 }, (_, index) => ({
    public_ref: `YOK-${100 + index}`,
    internal_id: 900 + index,
    title: `finished ${index}`,
    project: "yoke",
    project_id: 1,
    project_sequence: 100 + index,
    workflow_id: "issue",
    status: "done",
    created_at: new Date(Date.now() - 86400000).toISOString(),
    updated_at: new Date(Date.now() - 60000).toISOString(),
    // As the feed resolves them: terminal-ness and the finishing instant come
    // from the item's own pinned workflow definition, not from merged_at.
    terminal: true,
    finished: true,
    finished_at: new Date(Date.now() - (index + 1) * 60 * 1000).toISOString(),
  }));
  return {
    requests: base.requests,
    async call(request) {
      const callResult = await base.call(request);
      if (request.function !== "items.overview.list") return callResult;
      return {
        ...callResult,
        envelope: {
          ...callResult.envelope,
          result: { rows: [...callResult.envelope.result.rows, ...done] },
        },
      };
    },
  };
}

test("a full-roster scope reaches the Items see-more link as All", async (t) => {
  stubFetch(t);
  const documentNode = new FakeDocument();
  const client = overflowingDoneClient();
  const { root, mounted } = await mountAt(
    documentNode, "#/frontier?project=1,2", client,
  );
  const seeMore = byClass(root, "see-more-card")[0];
  assert.ok(seeMore, "the Done band should overflow into a see-more card");
  // All is the absent parameter in an authored route; the shell's own link
  // rewrite spells it `project=all` when it resolves the click. What must
  // never appear here is a member list naming the roster.
  assert.equal(seeMore.href, "#/items");
  mounted.unmount();
});
