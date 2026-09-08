import assert from "node:assert/strict";
import test from "node:test";

import {
  renderOuroborosView,
  OUROBOROS_PAGE_SIZE,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_ouroboros.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
  visibleText,
} from "./universe_ui_dom_test_support.mjs";

function ouroborosContext(documentNode, call, projects) {
  return {
    client: { call },
    document: documentNode,
    isMounted: () => true,
    projects: () => projects || [{
      id: 1, slug: "yoke", name: "Yoke",
    }],
    capabilities: {},
  };
}

function page(entries, { matchingCount, cursor = null } = {}) {
  return {
    status: 200,
    envelope: {
      success: true,
      result: {
        entries,
        matching_count: matchingCount,
        next_cursor: cursor,
      },
    },
  };
}

function loadMoreButton(root) {
  const host = byClass(root, "item-roster-more")[0];
  return host?.children.find((node) => node.tagName === "BUTTON") || null;
}

function reviewSelect(root) {
  return allNodes(root).find((node) => node.tagName === "SELECT");
}

test("the first read asks for a compact roster page and reports matching vs loaded", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderOuroborosView(ouroborosContext(documentNode, async (request) => {
    requests.push(request);
    return page(
      [{ id: 9, timestamp: "now", category: "observation", agent: "t", context: "c" }],
      { matchingCount: 120, cursor: "c1" },
    );
  }), root, ["1"]);
  await settle();

  assert.equal(requests.length, 1);
  assert.equal(requests[0].payload.shape, "roster");
  assert.equal(requests[0].payload.review_state, "all");
  assert.equal(requests[0].payload.limit, OUROBOROS_PAGE_SIZE);
  assert.equal("cursor" in requests[0].payload, false);
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 120");
  assert.match(
    byClass(root, "ouroboros-loaded-count")[0].textContent,
    /1 loaded of 120 matching/,
  );
  assert.ok(loadMoreButton(root), "a remaining cursor offers Load more");
});

test("Load more appends the next page without duplicating ids", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  const pages = [
    page(
      [{ id: 12, timestamp: "n", category: "a", agent: "t", context: "c" }],
      { matchingCount: 2, cursor: "c1" },
    ),
    page(
      [{ id: 8, timestamp: "o", category: "b", agent: "t", context: "c" }],
      { matchingCount: 2, cursor: null },
    ),
  ];
  renderOuroborosView(ouroborosContext(documentNode, async (request) => {
    requests.push(request);
    return pages[requests.length - 1];
  }), root, ["1"]);
  await settle();
  loadMoreButton(root).dispatchEvent(new Event("click"));
  await settle();

  assert.equal(requests[1].payload.cursor, "c1");
  const ids = byClass(root, "row-link")
    .filter((node) => node.href && node.href.includes("/ouroboros/"))
    .map((node) => node.href);
  assert.deepEqual(ids, ["#/ouroboros/12?project=1", "#/ouroboros/8?project=1"]);
  assert.equal(loadMoreButton(root), null);
});

test("changing review state resets loaded rows and the cursor", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderOuroborosView(ouroborosContext(documentNode, async (request) => {
    requests.push(request);
    if (request.payload.review_state === "unreviewed") {
      return page(
        [{ id: 3, timestamp: "open", category: "a", agent: "t", context: "c" }],
        { matchingCount: 1 },
      );
    }
    return page(
      [{ id: 9, timestamp: "all", category: "a", agent: "t", context: "c" }],
      { matchingCount: 9, cursor: "c1" },
    );
  }), root, ["1"]);
  await settle();
  loadMoreButton(root).dispatchEvent(new Event("click"));
  await settle();

  const review = reviewSelect(root);
  review.value = "unreviewed";
  review.dispatchEvent(new Event("change"));
  await settle();

  assert.equal("cursor" in requests[requests.length - 1].payload, false);
  assert.equal(requests[requests.length - 1].payload.review_state, "unreviewed");
  assert.match(visibleText(root, " "), /open/);
  assert.doesNotMatch(visibleText(root, " "), /\ball\b/);
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 1");
});

test("a stale response cannot overwrite newer criteria", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const pending = [];
  renderOuroborosView(ouroborosContext(documentNode, (request) => new Promise(
    (resolve) => pending.push({ request, resolve }),
  )), root, ["1"]);
  await settle();
  pending.shift().resolve(page(
    [{ id: 1, timestamp: "first", category: "a", agent: "t", context: "c" }],
    { matchingCount: 1 },
  ));
  await settle();

  const review = reviewSelect(root);
  review.value = "unreviewed";
  review.dispatchEvent(new Event("change"));
  await settle();
  review.value = "reviewed";
  review.dispatchEvent(new Event("change"));
  await settle();
  const [slow, fast] = pending;
  assert.equal(slow.request.payload.review_state, "unreviewed");
  assert.equal(fast.request.payload.review_state, "reviewed");
  fast.resolve(page(
    [{ id: 4, timestamp: "reviewed-row", category: "a", agent: "t", context: "c" }],
    { matchingCount: 1 },
  ));
  await settle();
  slow.resolve(page(
    [{ id: 5, timestamp: "unreviewed-row", category: "a", agent: "t", context: "c" }],
    { matchingCount: 99 },
  ));
  await settle();

  assert.match(visibleText(root, " "), /reviewed-row/);
  assert.doesNotMatch(visibleText(root, " "), /unreviewed-row/);
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 1");
});

test("a failed Load more keeps rendered rows and stays retryable", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  let calls = 0;
  renderOuroborosView(ouroborosContext(documentNode, async () => {
    calls += 1;
    if (calls === 2) {
      return {
        status: 503,
        envelope: { success: false, error: { message: "roster unavailable" } },
      };
    }
    return page(
      [{ id: calls, timestamp: `t${calls}`, category: "a", agent: "t", context: "c" }],
      { matchingCount: 9, cursor: "c1" },
    );
  }), root, ["1"]);
  await settle();
  loadMoreButton(root).dispatchEvent(new Event("click"));
  await settle();

  assert.match(visibleText(root, " "), /roster unavailable/);
  assert.match(visibleText(root, " "), /t1/);
  const retry = loadMoreButton(root);
  assert.ok(retry);
  retry.dispatchEvent(new Event("click"));
  await settle();
  assert.match(visibleText(root, " "), /t3/);
  assert.doesNotMatch(visibleText(root, " "), /roster unavailable/);
});

test("all-project scope fans out and merges newest id first", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  const projects = [
    { id: 1, slug: "alpha", name: "Alpha" },
    { id: 2, slug: "beta", name: "Beta" },
  ];
  renderOuroborosView(ouroborosContext(documentNode, async (request) => {
    requests.push(request);
    if (request.payload.project === "1") {
      return page(
        [{ id: 4, timestamp: "older-alpha", category: "a", agent: "t", context: "c", project: "alpha" }],
        { matchingCount: 1 },
      );
    }
    return page(
      [{ id: 10, timestamp: "newer-beta", category: "a", agent: "t", context: "c", project: "beta" }],
      { matchingCount: 1 },
    );
  }, projects), root, "all");
  await settle();

  assert.deepEqual(
    requests.map((request) => request.payload.project).sort(),
    ["1", "2"],
  );
  assert.equal(
    requests.some((request) => !request.payload.project),
    false,
  );
  const when = byClass(root, "row-link")
    .filter((node) => node.href && node.href.includes("/ouroboros/"))
    .map((node) => node.textContent);
  assert.deepEqual(when, ["newer-beta", "older-alpha"]);
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 2");
});

test("the mounted roster performs no polling", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderOuroborosView(ouroborosContext(documentNode, async (request) => {
    requests.push(request);
    return page(
      [{ id: 1, timestamp: "now", category: "a", agent: "t", context: "c" }],
      { matchingCount: 1 },
    );
  }), root, ["1"]);
  await settle();
  const afterMount = requests.length;
  await new Promise((resolve) => setTimeout(resolve, 80));
  await settle();
  assert.equal(requests.length, afterMount);
});
