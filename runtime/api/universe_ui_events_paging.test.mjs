import assert from "node:assert/strict";
import test from "node:test";

import {
  renderEventsView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_events.js";
import {
  EVENTS_PAGE_SIZE,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_events_history_loader.js";
import {
  SEARCH_DEBOUNCE_MS,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_shell_controls.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  ownTextContent,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function eventRow(name, createdAt, category = "system") {
  return {
    created_at: createdAt,
    event_name: name,
    category,
    severity: "INFO",
    context_label: `${name} happened`,
    target_kind: "universe",
    target_label: "Universe",
    target_id: "",
    target_project_id: null,
    source_label: "system",
    source_type: "system",
    project: "alpha",
  };
}

function page(rows, cursor = null) {
  return {
    status: 200,
    envelope: { success: true, result: { rows, next_cursor: cursor } },
  };
}

function failure(message = "events unavailable") {
  return { status: 500, envelope: { success: false, error: { message } } };
}

function eventsContext(documentNode, call, projects = [{ id: 1, slug: "alpha" }]) {
  return {
    client: { call },
    document: documentNode,
    isMounted: () => true,
    projects: () => projects,
    capabilities: {},
  };
}

function mount(call, { scope = "all", projects } = {}) {
  const documentNode = new FakeDocument();
  const root = documentNode.createElement("div");
  renderEventsView(eventsContext(documentNode, call, projects), root, scope);
  return root;
}

function entryNames(root) {
  return byClass(root, "event-name").map(ownTextContent);
}

function moreButton(root) {
  const host = byClass(root, "event-more")[0];
  return host?.children.find((node) => node.tagName === "BUTTON") || null;
}

function categoryButtons(root) {
  return byClass(root, "event-filter").map(ownTextContent);
}

function control(root, label) {
  const wrap = byClass(root, "event-criterion").find((node) => node.children.some(
    (child) => ownTextContent(child) === label,
  ));
  return wrap?.children.find(
    (node) => node.tagName === "SELECT" || node.tagName === "INPUT",
  ) || null;
}

async function settleDebounce() {
  await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 20));
  await settle();
}

test("the first read asks one page per authorized project bucket", async () => {
  const requests = [];
  const root = mount(async (request) => {
    requests.push(request);
    return page([eventRow(`E${requests.length}`, "2026-09-08T03:00:00Z")], "c1");
  }, { projects: [{ id: 1 }, { id: 2 }] });
  await settle();

  assert.deepEqual(requests.map((request) => request.payload.project), ["1", "2"]);
  for (const request of requests) {
    assert.equal(request.payload.history.limit, EVENTS_PAGE_SIZE);
    assert.equal("cursor" in request.payload.history, false);
  }
  assert.ok(moreButton(root), "a served cursor offers Load more");
});

test("Load more continues each bucket and merges newest first", async () => {
  const requests = [];
  const pages = {
    "1": [
      page([eventRow("alpha-new", "2026-09-08T05:00:00Z")], "a1"),
      page([eventRow("alpha-old", "2026-09-08T01:00:00Z")], null),
    ],
    "2": [
      page([eventRow("beta-new", "2026-09-08T04:00:00Z")], "b1"),
      page([eventRow("beta-old", "2026-09-08T02:00:00Z")], null),
    ],
  };
  const served = { 1: 0, 2: 0 };
  const root = mount(async (request) => {
    requests.push(request);
    const bucket = request.payload.project;
    return pages[bucket][served[bucket]++];
  }, { projects: [{ id: 1 }, { id: 2 }] });
  await settle();
  assert.deepEqual(entryNames(root), ["alpha-new", "beta-new"]);

  moreButton(root).dispatchEvent(new Event("click"));
  await settle();

  // Each bucket continued from its own cursor, never another bucket's.
  assert.deepEqual(
    requests.slice(2).map((request) => request.payload.history.cursor),
    ["a1", "b1"],
  );
  const names = entryNames(root);
  assert.deepEqual(names, ["alpha-new", "beta-new", "beta-old", "alpha-old"]);
  assert.equal(new Set(names).size, names.length);
  // Every cursor is spent, so the control is gone rather than dead.
  assert.equal(moreButton(root), null);
});

test("category buttons count and refine the loaded entries, and say so", async () => {
  const root = mount(async () => page([
    eventRow("Deployed", "2026-09-08T05:00:00Z", "delivery"),
    eventRow("Claimed", "2026-09-08T04:00:00Z", "sessions"),
    eventRow("Released", "2026-09-08T03:00:00Z", "delivery"),
  ]));
  await settle();

  assert.equal(byClass(root, "event-filter-scope")[0].textContent, "Loaded entries:");
  assert.deepEqual(categoryButtons(root), [
    "All · 3 loaded", "Sessions · 1 loaded", "Delivery · 2 loaded",
  ]);

  const delivery = byClass(root, "event-filter").find(
    (node) => node.attributes.get("data-category") === "delivery",
  );
  delivery.dispatchEvent(new Event("click"));

  assert.deepEqual(entryNames(root), ["Deployed", "Released"]);
  const pressed = byClass(root, "event-filter").filter(
    (node) => node.attributes.get("aria-pressed") === "true",
  );
  assert.deepEqual(pressed.map(ownTextContent), ["Delivery · 2 loaded"]);
});

test("a criterion change restarts paging and rides the request", async () => {
  const requests = [];
  const root = mount(async (request) => {
    requests.push(request);
    if (request.payload.min_severity === "ERROR") {
      return page([eventRow("ItFailed", "2026-09-08T01:00:00Z")]);
    }
    return page([eventRow("Routine", "2026-09-08T05:00:00Z")], "c1");
  });
  await settle();
  moreButton(root).dispatchEvent(new Event("click"));
  await settle();

  const severity = control(root, "Severity");
  severity.value = "ERROR";
  severity.dispatchEvent(new Event("change"));
  await settle();

  const last = requests[requests.length - 1];
  assert.equal(last.payload.min_severity, "ERROR");
  assert.equal("cursor" in last.payload.history, false);
  assert.deepEqual(entryNames(root), ["ItFailed"]);
  assert.equal(moreButton(root), null);
});

test("a typed criterion debounces and a stale reply cannot win", async () => {
  const pending = [];
  const root = mount((request) => new Promise(
    (resolve) => pending.push({ request, resolve }),
  ));
  await settle();
  pending.shift().resolve(page([eventRow("Mounted", "2026-09-08T05:00:00Z")]));
  await settle();

  const eventName = control(root, "Event");
  eventName.value = "Slow";
  eventName.dispatchEvent(new Event("input"));
  await settleDebounce();
  eventName.value = "Fast";
  eventName.dispatchEvent(new Event("input"));
  await settleDebounce();
  assert.equal(pending.length, 2, "each settled burst sent exactly one request");

  const [slow, fast] = pending;
  fast.resolve(page([eventRow("FastResult", "2026-09-08T04:00:00Z")]));
  await settle();
  slow.resolve(page([eventRow("SlowResult", "2026-09-08T03:00:00Z")]));
  await settle();

  assert.deepEqual(entryNames(root), ["FastResult"]);
});

test("a failed Load more keeps the loaded entries and offers a retry", async () => {
  let calls = 0;
  const root = mount(async () => {
    calls += 1;
    if (calls === 2) return failure();
    return page([eventRow(`E${calls}`, `2026-09-08T0${5 - calls}:00:00Z`)], "c1");
  });
  await settle();

  moreButton(root).dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(entryNames(root), ["E1"]);
  assert.equal(byClass(root, "error").length, 1);
  const retry = moreButton(root);
  assert.equal(retry.textContent, "Retry");

  retry.dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(entryNames(root), ["E1", "E3"]);
  assert.equal(byClass(root, "error").length, 0);
});

test("a failed first page names the failure and the way back", async () => {
  const root = mount(async () => failure("history cursor is invalid"));
  await settle();

  assert.equal(byClass(root, "error").length, 1);
  assert.match(
    byClass(root, "event-recovery")[0].textContent,
    /Reload the first page/,
  );
  assert.equal(entryNames(root).length, 0);
  // The criteria controls survive the failure, so the reader can change one.
  assert.ok(control(root, "Severity"));
});

test("mount and filter changes never start a poll", async () => {
  const requests = [];
  const root = mount(async (request) => {
    requests.push(request);
    return page([eventRow("Once", "2026-09-08T05:00:00Z")]);
  });
  await settle();
  assert.equal(requests.length, 1);

  const since = control(root, "Since");
  since.value = "24 hours ago";
  since.dispatchEvent(new Event("change"));
  await settle();
  assert.equal(requests.length, 2);

  await new Promise((resolve) => setTimeout(resolve, 400));
  await settle();
  assert.equal(requests.length, 2, "a settled view issues no further reads");
});

test("a single-project scope reads that project and nothing wider", async () => {
  const requests = [];
  mount(async (request) => {
    requests.push(request);
    return page([]);
  }, { scope: ["7"] });
  await settle();

  assert.deepEqual(requests.map((request) => request.payload.project), ["7"]);
});

test("the panel shows no total it cannot honestly serve", async () => {
  const root = mount(async () => page(
    [eventRow("Only", "2026-09-08T05:00:00Z")],
    "more-behind-this",
  ));
  await settle();

  assert.equal(byClass(root, "panel-count").length, 0);
});

test("allNodes finds the timeline entries the view renders", async () => {
  const root = mount(async () => page([eventRow("Rendered", "2026-09-08T05:00:00Z")]));
  await settle();

  assert.equal(byClass(root, "event-entry").length, 1);
  assert.ok(allNodes(root).some((node) => node.classList.contains("event-timeline")));
});
