// One card renderer for every session, and one count for how much of the
// current filter is on screen. Both are things a status branch used to own:
// an ended session was drawn in a simpler shape, and its page count was a
// sentence beside the tile that already reported the page.
import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function pageClient(handlers) {
  return {
    async call(request) {
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      const handler = handlers[request.function];
      if (!handler) throw new Error(`unexpected function ${request.function}`);
      return handler(request);
    },
  };
}

async function mountSessions(t, handlers) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client: pageClient(handlers) });
  await settle();
  return { root, mounted };
}

function statValues(root) {
  return byClass(root, "stat").map((tile) => [
    byClass(tile, "n")[0].textContent, byClass(tile, "l")[0].textContent,
  ]);
}

const BASE_ROW = {
  project: "yoke", project_id: 1, executor: "codex",
  executor_surface: "codex-cli", execution_lane: "DARIUS",
  executor_mark: "X", executor_class_name: "h-codex",
  actor_id: 1, actor_kind: "human", actor_label: "Ben",
  model: "gpt-5.6-sol", machine_id: "m1", machine_name: "studio",
  activity_at: "2026-08-22T12:00:00Z",
  recent_item: "YOK-1", recent_item_title: "A worked item",
  holdings: {
    current: [{
      holding_kind: "work_claim", target_kind: "item", target: "YOK-1",
      claimed_at: "2026-08-22T11:00:00Z",
    }],
    previous: [], previous_remainder: 0,
  },
};

// Every section an ended card can fill, it fills — in the same classes and
// the same order as a live one. A section list that an ended session skipped
// wholesale is what made its card read as a different kind of object.
const SHARED_SECTIONS = [
  "session-top", "session-harness", "session-executor", "session-lane",
  "session-operator", "session-card-body", "session-state-line",
  "session-model", "session-holdings-group", "session-relay", "session-age",
];

test("an ended card is composed from the same sections as a live one", () => {
  const documentNode = new FakeDocument();
  const active = sessionCard(documentNode, {
    ...BASE_ROW, session_id: "live-1", liveness: "active",
    current_item: "YOK-1", messageability: { messageable: true },
  }, () => {});
  const ended = sessionCard(documentNode, {
    ...BASE_ROW, session_id: "ended-1", liveness: "ended",
    ended_cause: "wound_down", ended_at: "2026-08-22T12:00:00Z",
  }, () => {});

  assert.equal(ended.className, active.className);
  for (const section of SHARED_SECTIONS) {
    assert.ok(byClass(active, section).length, `live card lacks ${section}`);
    assert.ok(byClass(ended, section).length, `ended card lacks ${section}`);
  }
  // Truthful about what ended: no live action is offered, and the reason
  // names the end rather than blaming the harness for a missing route.
  assert.equal(
    allNodes(ended).find(
      (node) => node.tagName === "BUTTON" && node.textContent === "Message",
    ),
    undefined,
  );
  assert.equal(
    byClass(ended, "session-messaging-blocked")[0].textContent,
    "Messaging unavailable: this session has ended and cannot be restarted "
    + "from here.",
  );
  // A relay warning is a live session's alarm; an ended card still names its
  // machine without raising one.
  assert.equal(byClass(ended, "session-relay-warning").length, 0);
  assert.match(
    byClass(ended, "session-relay-pill")[0].className, /\bidle\b/,
  );
  assert.match(byClass(ended, "session-age")[0].textContent, /^ended /);
});

test("the sessions-shown tile carries the page against the filtered match", async (t) => {
  const endedRow = (index) => ({
    ...BASE_ROW, session_id: `ended-${index}`, liveness: "ended",
    ended_cause: "wound_down", ended_at: "2026-08-22T12:00:00Z",
    actor_id: index, holdings: { current: [], previous: [], previous_remainder: 0 },
  });
  let served = 0;
  const { root, mounted } = await mountSessions(t, {
    "session_control.relay.list": () => ok({ relays: [] }),
    "sessions.list": (request) => {
      if (request.payload.ended_last_24h) return ok({ rows: [] });
      if (request.payload.open) {
        return ok({ rows: [{
          ...BASE_ROW, session_id: "live-1", liveness: "active",
          messageability: { messageable: true },
        }] });
      }
      const page = [endedRow(served + 1), endedRow(served + 2)];
      served += 2;
      return ok({
        rows: page, matched_count: 4758,
        next_cursor: served < 4 ? `cursor-${served}` : null,
        facets: { projects: [], harnesses: [], machines: [] },
      });
    },
  });

  const stateField = byClass(root, "session-roster-filter").find(
    (field) => field.children[0]?.textContent === "State",
  );
  const state = stateField.children[1];
  state.value = "ended";
  state.dispatchEvent(new Event("change"));
  await settle();
  assert.deepEqual(statValues(root)[0], ["2 of 4,758", "sessions shown"]);
  // The tile is the only place the page count is stated.
  assert.equal(byClass(root, "sessions-history-status").length, 0);

  const loadMore = allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Load more",
  );
  loadMore.dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(statValues(root)[0], ["4 of 4,758", "sessions shown"]);

  // Unfiltered counts open and ended rows together, so its denominator means
  // the same thing as either single-state one.
  state.value = "";
  state.dispatchEvent(new Event("change"));
  await settle();
  assert.deepEqual(statValues(root)[0], ["5 of 4,759", "sessions shown"]);
  mounted.unmount();
});
