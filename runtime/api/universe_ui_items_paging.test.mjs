import assert from "node:assert/strict";
import test from "node:test";

import {
  renderItemsView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_items.js";
import {
  ROSTER_PAGE_SIZE,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_items_roster_loader.js";
import {
  SEARCH_DEBOUNCE_MS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_shell_controls.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { itemContext, itemText } from "./universe_ui_items_test_support.mjs";

function row(ref) {
  return {
    public_ref: ref,
    project_id: 7,
    project: "acme",
    title: `title ${ref}`,
    workflow_id: "issue",
    status: "idea",
    stage_label: "Idea",
    owner: "",
    claimed_by: null,
  };
}

// `filters: null` is what a continuation actually returns: the choices
// describe a scope the cursor did not change, so the server sends them once
// and the loader keeps what it already holds.
function page(rows, { matchCount, cursor = null, filters = {
  workflow_ids: ["issue", "dash"],
  statuses: [{ id: "idea", label: "Idea" }],
} }) {
  return {
    status: 200,
    envelope: {
      success: true,
      result: {
        rows,
        count: rows.length,
        match_count: matchCount,
        next_cursor: cursor,
        filters,
      },
    },
  };
}

// The control sits beside any failure notice in the same container, so find
// the button itself rather than whichever child happens to come first.
function loadMoreButton(root) {
  const host = byClass(root, "item-roster-more")[0];
  return host?.children.find((node) => node.tagName === "BUTTON") || null;
}

function openFilters(root) {
  allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Filter ▾",
  ).dispatchEvent(new Event("click"));
}

function searchBox(root) {
  return allNodes(root).find(
    (node) => node.tagName === "INPUT" && node.type === "search",
  );
}

async function settleDebounce() {
  await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 20));
  await settle();
}

test("the first read asks for one page and reports the total behind it", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemsView(itemContext(documentNode, async (request) => {
    requests.push(request);
    return page([row("ACM-1")], { matchCount: 120, cursor: "c1" });
  }), root, "all");
  await settle();

  assert.equal(requests.length, 1);
  assert.equal(requests[0].payload.page_size, ROSTER_PAGE_SIZE);
  assert.equal("cursor" in requests[0].payload, false);
  // The heading reports what matches, not what has loaded.
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 120");
  assert.ok(loadMoreButton(root), "a remaining cursor offers Load more");
});

test("Load more appends the next page and retires when the cursor runs out", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  const pages = [
    page([row("ACM-1"), row("ACM-2")], { matchCount: 4, cursor: "c1" }),
    // The continuation carries no choices, as the server actually sends it.
    page([row("ACM-3"), row("ACM-4")], {
      matchCount: 4, cursor: null, filters: null,
    }),
  ];
  renderItemsView(itemContext(documentNode, async (request) => {
    requests.push(request);
    return pages[requests.length - 1];
  }), root, "all");
  await settle();
  assert.equal(byClass(root, "item-roster-row").length, 2);

  loadMoreButton(root).dispatchEvent(new Event("click"));
  await settle();

  // The second request continues the sequence from the served cursor.
  assert.equal(requests[1].payload.cursor, "c1");
  // Appended, not replaced, and no row arrives twice.
  const refs = byClass(root, "row-link").map((node) => node.textContent);
  assert.deepEqual(refs, ["ACM-1", "ACM-2", "ACM-3", "ACM-4"]);
  assert.equal(new Set(refs).size, refs.length);
  // No cursor remains, so the control is gone rather than dead.
  assert.equal(loadMoreButton(root), null);

  // The choices the continuation omitted are still on the controls.
  openFilters(root);
  const workflow = allNodes(root).find(
    (node) => node.tagName === "SELECT" &&
      node.children[0]?.textContent === "All workflows",
  );
  assert.deepEqual(
    workflow.children.map((node) => node.textContent),
    ["All workflows", "issue", "dash"],
  );
});

test("changing a criterion resets the loaded rows and the paging sequence", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemsView(itemContext(documentNode, async (request) => {
    requests.push(request);
    if (request.payload.cursor) {
      return page([row("ACM-2")], { matchCount: 9, cursor: "c2" });
    }
    if (request.payload.workflow) {
      return page([row("ACM-9")], { matchCount: 1, cursor: null });
    }
    return page([row("ACM-1")], { matchCount: 9, cursor: "c1" });
  }), root, "all");
  await settle();
  loadMoreButton(root).dispatchEvent(new Event("click"));
  await settle();
  assert.equal(byClass(root, "item-roster-row").length, 2);

  openFilters(root);
  const workflow = allNodes(root).find(
    (node) => node.tagName === "SELECT" &&
      node.children[0]?.textContent === "All workflows",
  );
  workflow.value = "dash";
  workflow.dispatchEvent(new Event("change"));
  await settle();

  // The accumulated pages are dropped and paging restarts with no cursor.
  assert.equal(byClass(root, "item-roster-row").length, 1);
  assert.match(itemText(root), /ACM-9/);
  assert.doesNotMatch(itemText(root), /ACM-1\b/);
  assert.equal("cursor" in requests[requests.length - 1].payload, false);
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 1");
});

test("a stale response cannot overwrite newer criteria", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const pending = [];
  renderItemsView(itemContext(documentNode, (request) => new Promise(
    (resolve) => pending.push({ request, resolve }),
  )), root, "all");
  await settle();

  // Resolve the initial read so the controls are mounted.
  pending.shift().resolve(page([row("ACM-1")], { matchCount: 1 }));
  await settle();
  openFilters(root);
  const search = searchBox(root);

  search.value = "slow";
  search.dispatchEvent(new Event("input"));
  await settleDebounce();
  search.value = "fast";
  search.dispatchEvent(new Event("input"));
  await settleDebounce();
  assert.equal(pending.length, 2, "both searches were sent");

  const [slow, fast] = pending;
  assert.equal(slow.request.payload.search, "slow");
  assert.equal(fast.request.payload.search, "fast");
  // The newer answer lands first, then the older one arrives late.
  fast.resolve(page([row("ACM-FAST")], { matchCount: 1 }));
  await settle();
  slow.resolve(page([row("ACM-SLOW")], { matchCount: 99 }));
  await settle();

  assert.match(itemText(root), /ACM-FAST/);
  assert.doesNotMatch(itemText(root), /ACM-SLOW/);
  assert.equal(byClass(root, "panel-count")[0].textContent, "· 1");
});

test("typed input is debounced into one request per burst", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemsView(itemContext(documentNode, async (request) => {
    requests.push(request);
    return page([row("ACM-1")], { matchCount: 1 });
  }), root, "all");
  await settle();
  openFilters(root);
  const search = searchBox(root);

  for (const value of ["s", "sh", "shi", "ship"]) {
    search.value = value;
    search.dispatchEvent(new Event("input"));
  }
  await settleDebounce();

  assert.equal(requests.length, 2, "the burst collapsed into one reload");
  assert.equal(requests[1].payload.search, "ship");
});

test("a failed Load more keeps the loaded rows and stays retryable", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  let calls = 0;
  renderItemsView(itemContext(documentNode, async () => {
    calls += 1;
    if (calls === 2) {
      return {
        status: 503,
        envelope: { success: false, error: { message: "roster unavailable" } },
      };
    }
    return page([row(`ACM-${calls}`)], { matchCount: 9, cursor: "c1" });
  }), root, "all");
  await settle();
  assert.equal(byClass(root, "item-roster-row").length, 1);
  loadMoreButton(root).dispatchEvent(new Event("click"));
  await settle();

  // The failure is surfaced rather than swallowed...
  assert.match(itemText(root), /roster unavailable/);
  // ...the row that was already on screen is still on screen...
  assert.equal(byClass(root, "item-roster-row").length, 1);
  assert.match(itemText(root), /ACM-1/);
  // ...and the control is still there to try again with.
  const retry = loadMoreButton(root);
  assert.ok(retry, "Load more survives a failed page");
  assert.equal(retry.disabled, false);

  retry.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(byClass(root, "item-roster-row").length, 2);
  assert.doesNotMatch(itemText(root), /roster unavailable/);
});

test("an initial failure replaces the table rather than sitting at loading", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  renderItemsView(itemContext(documentNode, async () => ({
    status: 503,
    envelope: { success: false, error: { message: "roster unavailable" } },
  })), root, "all");
  await settle();

  assert.match(itemText(root), /roster unavailable/);
  assert.equal(byClass(root, "item-roster-row").length, 0);
  assert.doesNotMatch(itemText(root), /loading/);
});

test("the mounted roster performs no polling", async () => {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  const requests = [];
  renderItemsView(itemContext(documentNode, async (request) => {
    requests.push(request);
    return page([row("ACM-1")], { matchCount: 1 });
  }), root, "all");
  await settle();
  const afterMount = requests.length;

  await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS * 4));
  await settle();

  assert.equal(requests.length, afterMount, "the roster re-read itself");
});
