import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument, allNodes, byClass, response, settle,
} from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const failed = (message = "retry history") => ({
  status: 503,
  envelope: { success: false, error: { code: "history_unavailable", message } },
});
const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function row(sessionId, liveness = "ended") {
  return {
    session_id: sessionId, liveness, project_id: 1, project: "yoke",
    executor: "codex", executor_surface: "codex-cli", model: "gpt-5.6-sol",
    actor_id: 2, actor_kind: "human", actor_label: "Ben",
    machine_id: "machine-1", machine_name: "studio",
    activity_at: "2026-09-08T01:00:00Z", ended_cause: "wound_down",
    messageability: { messageable: true, wake_available: true }, claims: [],
  };
}

function history(rows, matchedCount, nextCursor = null) {
  return ok({
    fields: [], rows, matched_count: matchedCount, next_cursor: nextCursor,
    facets: {
      projects: [{ id: 1, slug: "yoke" }], harnesses: ["codex", "codex-cli"],
      machines: [{ id: "machine-1", label: "studio" }],
    },
  });
}

async function mountHistory(t, handler) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "session_control.relay.list") return ok({ relays: [] });
      if (request.function === "machine.list") return ok({ machines: [] });
      // The actor menu's own read at mount; not part of the history story.
      if (request.function === "profile.get") return failed();
      if (request.function === "ui_preferences.screen_selection.list") return ok({ views: {} });
      if (request.function === "ui_preferences.screen_selection.set") return ok({});
      return handler(request);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { root, requests, mounted };
}

function control(root, label) {
  const field = byClass(root, "session-roster-filter").find(
    (node) => node.children[0]?.textContent === label,
  );
  return field.children[1];
}

function button(root, label) {
  return allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === label,
  );
}

const cardIds = (root) => byClass(root, "session-card").map(
  (card) => card.getAttribute("data-session-id"),
);

test("ended history is lazy, cursor-paged, and excluded from bulk audiences", async (t) => {
  const open = [row("open-active", "active"), row("open-stale", "stale")];
  const { root, requests, mounted } = await mountHistory(t, (request) => {
    if (request.function === "sessions.list" && request.payload.open) return ok({ rows: open });
    if (request.function === "sessions.list" && request.payload.history) {
      return request.payload.history.cursor
        ? history([row("ended-3")], 3)
        : history([row("ended-1"), row("ended-2")], 3, "page-2");
    }
    if (request.function === "session_control.message.preview") {
      return ok({ recipients: open, recipient_count: 2, confirmation_token: "open-only" });
    }
    throw new Error(`unexpected function ${request.function}`);
  });
  assert.deepEqual(requests.filter((request) => request.function === "sessions.list"), [{
    function: "sessions.list", payload: { open: true, projects: ["1"] },
  }]);
  assert.deepEqual(cardIds(root), ["open-active", "open-stale"]);

  const state = control(root, "State");
  state.value = "ended";
  state.dispatchEvent(new Event("change"));
  await settle();
  const firstHistory = requests.find((request) => request.payload.history);
  assert.deepEqual(firstHistory.payload.history, {
    limit: 50, cursor: null, search: "", projects: ["1"], harnesses: [], machines: [],
  });
  assert.deepEqual(cardIds(root), ["ended-1", "ended-2"]);
  // The page against its match is the sessions-shown tile's own value; the
  // status paragraph is left for loading and failure, which this is neither.
  assert.equal(byClass(root, "sessions-history-status").length, 0);
  assert.equal(byClass(byClass(root, "stat")[0], "n")[0].textContent, "2 of 3");
  button(root, "Load more").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(cardIds(root), ["ended-1", "ended-2", "ended-3"]);
  assert.equal(button(root, "Load more").hidden, true);

  state.value = "";
  state.dispatchEvent(new Event("change"));
  assert.deepEqual(cardIds(root), ["open-active", "open-stale", "ended-1", "ended-2", "ended-3"]);
  button(root, "Message all").dispatchEvent(new Event("click"));
  await settle();
  const preview = requests.find((request) => request.function === "session_control.message.preview");
  assert.deepEqual(preview.payload.selector, { session_ids: ["open-active", "open-stale"] });
  mounted.unmount();
});

test("reclaim refreshes open rows without resetting loaded history", async (t) => {
  let openReads = 0;
  const { root, requests, mounted } = await mountHistory(t, (request) => {
    if (request.function === "sessions.list" && request.payload.open) {
      openReads += 1;
      return ok({ rows: openReads === 1 ? [row("stale", "stale")] : [] });
    }
    if (request.function === "sessions.list") return history([row("ended")], 2, "next");
    if (request.function === "sessions.reclaim_stale") return ok({ total_reclaimed: 1 });
    throw new Error(`unexpected function ${request.function}`);
  });
  const state = control(root, "State");
  state.value = "ended";
  state.dispatchEvent(new Event("change"));
  await settle();
  button(root, "Reclaim stale").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(cardIds(root), ["ended"]);
  assert.equal(requests.filter((request) => request.payload?.history).length, 1);
  assert.equal(requests.filter((request) => request.payload?.open).length, 2);
  assert.equal(button(root, "Load more").hidden, false);
  mounted.unmount();
});

test("a failed reclaim refresh preserves rows and reports recovery", async (t) => {
  let openReads = 0;
  const { root, mounted } = await mountHistory(t, (request) => {
    if (request.function === "sessions.list" && request.payload.open) {
      openReads += 1;
      return openReads === 1 ? ok({ rows: [row("stale", "stale")] })
        : failed("open-session refresh failed; retry reclaim");
    }
    if (request.function === "sessions.reclaim_stale") return ok({ total_reclaimed: 1 });
    throw new Error(`unexpected function ${request.function}`);
  });
  button(root, "Reclaim stale").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(cardIds(root), ["stale"]);
  assert.match(byClass(root, "sessions-action-status")[0].textContent,
    /open-session refresh failed; retry reclaim/);
  mounted.unmount();
});

test("new search criteria discard an older in-flight history response", async (t) => {
  const pending = new Map();
  const { root, mounted } = await mountHistory(t, (request) => {
    if (request.payload.open) return ok({ rows: [] });
    const search = request.payload.history.search;
    if (!search) return history([], 0);
    return new Promise((resolve) => pending.set(search, resolve));
  });
  const state = control(root, "State");
  state.value = "ended";
  state.dispatchEvent(new Event("change"));
  await settle();
  const search = byClass(root, "session-filter-search")[0].children[1];
  search.value = "older";
  search.dispatchEvent(new Event("input"));
  await delay(275);
  search.value = "newer";
  search.dispatchEvent(new Event("input"));
  await delay(275);
  pending.get("newer")(history([row("newer-result")], 1));
  await settle();
  pending.get("older")(history([row("older-result")], 1));
  await settle();
  assert.deepEqual(cardIds(root), ["newer-result"]);
  mounted.unmount();
});

test("first-page and load-more failures preserve data and remain retryable", async (t) => {
  let calls = 0;
  const { root, mounted } = await mountHistory(t, (request) => {
    if (request.payload.open) return ok({ rows: [row("open", "active")] });
    calls += 1;
    if (calls === 1 || calls === 3) return failed();
    if (calls === 2) return history([row("ended-1")], 2, "next");
    return history([row("ended-2")], 2);
  });
  const state = control(root, "State");
  state.value = "ended";
  state.dispatchEvent(new Event("change"));
  await settle();
  assert.equal(button(root, "Retry history").hidden, false);
  button(root, "Retry history").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(cardIds(root), ["ended-1"]);
  button(root, "Load more").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(cardIds(root), ["ended-1"]);
  button(root, "Retry load more").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(cardIds(root), ["ended-1", "ended-2"]);
  mounted.unmount();
});
