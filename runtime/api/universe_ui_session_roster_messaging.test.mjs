import { setStatuses, statusChecks } from "./universe_ui_sessions_view_test_support.mjs";
import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
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

function button(root, label) {
  return allNodes(root).find(
    (node) => node.tagName === "BUTTON" && node.textContent === label,
  );
}

function sessionRow(sessionId, liveness, overrides = {}) {
  return {
    session_id: sessionId,
    liveness,
    session_state: {status: liveness === "ended" ? "ended" : "waiting", active_at: null, reason: "Waiting for direction."},
    executor: "codex",
    executor_surface: "codex-cli",
    model: "gpt-5.6-sol",
    execution_level: "ALTMAN",
    mode: "dash",
    actor_id: 2,
    actor_kind: "human",
    actor_label: "Ben",
    project_id: 1,
    project: "yoke",
    current_item: null,
    claims: [],
    machine_id: "machine-1",
    machine_name: "studio",
    activity_at: "2026-08-27T12:00:00Z",
    messageability: { messageable: true, wake_available: true },
    ...overrides,
  };
}

async function mountRoster(t, rows, requests, handlers = {}) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = "/sessions?project=1";
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "sessions.list") {
        if (request.payload.usage_last_24h) return ok({ rows: [] });
        if (request.payload.history) {
          let ended = rows.filter((row) => row.liveness === "ended");
          const harness = request.payload.history.harnesses?.[0];
          if (harness) ended = ended.filter((row) => [
            row.executor, row.executor_surface,
          ].includes(harness));
          return ok({
            fields: [], rows: ended, matched_count: ended.length,
            next_cursor: null,
            facets: {
              projects: [{ id: 1, slug: "yoke" }],
              harnesses: ["codex", "codex-cli", "cursor", "cursor-desktop", "cursor-cli"],
              machines: [{ id: "machine-1", label: "studio" }],
            },
          });
        }
        return ok({
          rows: rows.filter((row) => row.liveness !== "ended"),
        });
      }
      const handler = handlers[request.function];
      if (!handler) throw new Error(`unexpected function ${request.function}`);
      return handler(request);
    },
  };
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { root, mounted };
}

function cardIds(root) {
  return byClass(root, "session-card").map(
    (card) => card.getAttribute("data-session-id"),
  );
}

test("roster defaults to Open and exposes only the supported filters", async (t) => {
  const requests = [];
  const rows = [
    sessionRow("active-codex", "active"),
    sessionRow("stale-cursor", "stale", {
      executor: "cursor", executor_surface: "cursor-desktop",
    }),
    sessionRow("ended-cursor", "ended", {
      executor: "claude-code", executor_surface: "cursor-cli",
    }),
  ];
  const { root, mounted } = await mountRoster(t, rows, requests);
  const fields = byClass(root, "session-roster-filter");
  assert.deepEqual(
    fields.map((field) => field.classList.contains("session-filter-search")
      ? "Search" : field.children[0].textContent),
    ["Search", "Project", "Harness", "Machine"],
  );
  assert.deepEqual(statusChecks(root).map((check) => [check.value, check.checked]),
    [["working", true], ["waiting", true], ["ended", false]]);
  assert.deepEqual(cardIds(root), ["active-codex", "stale-cursor"]);
  const staleCard = byClass(root, "session-card").find(
    (card) => card.getAttribute("data-session-id") === "stale-cursor",
  );
  assert.equal(staleCard.classList.contains("is-stale"), false);
  assert.deepEqual(byClass(staleCard, "session-status-pill").map((pill) => pill.textContent),
    ["Waiting"]);
  // One roster read, this view's own scoped load; the page's durable 24h
  // spend read fires beside it, because the window it answers for is not
  // the filtered roster. The app-wide steering-color read
  // (context.refreshSteeringGroupColors) asks its own narrow question.
  assert.deepEqual(
    requests.filter((request) => request.function === "sessions.list")
      .map((request) => request.payload),
    [
      { open: true, detail: "full", projects: ["1"] },
      { usage_last_24h: true, projects: ["1"] },
    ],
  );

  setStatuses(root, ["working", "waiting", "ended"]);
  await settle();
  assert.deepEqual(
    cardIds(root), ["active-codex", "stale-cursor", "ended-cursor"],
  );
  const anyStaleCard = byClass(root, "session-card").find(
    (card) => card.getAttribute("data-session-id") === "stale-cursor",
  );
  assert.equal(anyStaleCard.classList.contains("is-stale"), false);
  assert.equal(byClass(anyStaleCard, "session-stale-pill").length, 0);
  setStatuses(root, ["ended"]);
  await settle();
  assert.deepEqual(cardIds(root), ["ended-cursor"]);
  setStatuses(root, ["working", "waiting", "ended"]);
  await settle();
  const harness = fields.find(
    (field) => field.children[0].textContent === "Harness",
  ).children[1];
  harness.value = "cursor";
  harness.dispatchEvent(new Event("input"));
  await settle();
  assert.deepEqual(cardIds(root), ["stale-cursor"]);
  assert.equal(
    button(root, "Message all").parentNode.getAttribute("data-tooltip"),
    "Message all 1 open session",
  );

  button(root, "Clear").dispatchEvent(new Event("click"));
  assert.deepEqual(statusChecks(root).map((check) => check.checked), [true, true, false]);
  assert.equal(harness.value, "");
  assert.deepEqual(cardIds(root), ["active-codex", "stale-cursor"]);
  assert.equal(
    allNodes(root).some((node) => node.textContent === "Blitz worktree lanes"),
    false,
  );
  mounted.unmount();
});

test("Message all sends to the exact current roster result without a preview step", async (t) => {
  const requests = [];
  const rows = [
    sessionRow("active-cursor", "active", { executor: "cursor" }),
    sessionRow("active-claude", "active", { executor: "claude-code" }),
    sessionRow("stale-cursor", "stale", { executor_surface: "cursor-desktop" }),
  ];
  const handlers = {
    "session_control.message.preview": (request) => ok({
      recipients: request.payload.selector.session_ids.map((sessionId) => ({
        ...rows.find((row) => row.session_id === sessionId),
      })),
      recipient_count: request.payload.selector.session_ids.length,
      confirmation_token: "confirmed-filtered-roster",
    }),
    "session_control.message.send": () => ok({
      message_id: "message-filtered", recipient_count: 2, recipients: [],
    }),
  };
  const { root, mounted } = await mountRoster(t, rows, requests, handlers);
  const fields = byClass(root, "session-roster-filter");
  const harness = fields.find(
    (field) => field.children[0].textContent === "Harness",
  ).children[1];
  setStatuses(root, ["working", "waiting", "ended"]);
  await settle();
  harness.value = "cursor";
  harness.dispatchEvent(new Event("input"));
  await settle();

  button(root, "Message all").dispatchEvent(new Event("click"));
  await settle();
  const preview = requests.find(
    (request) => request.function === "session_control.message.preview",
  );
  assert.deepEqual(preview.payload.selector, {
    session_ids: ["active-cursor", "stale-cursor"],
  });
  assert.equal(
    byClass(root, "session-message-filter-summary")[0].textContent,
    "Filters: Status: working, waiting, ended · Harness: cursor",
  );
  assert.equal(byClass(root, "session-message-preview-list")[0].children.length, 2);
  assert.equal(button(root, "Preview recipients"), undefined);
  assert.equal(byClass(root, "session-message-selector-sessions").length, 0);

  const body = byClass(root, "session-message-body")[0];
  const sendButton = button(root, "Send message");
  assert.equal(sendButton.disabled, true);
  body.value = "Inspect the current roster audience.";
  body.dispatchEvent(new Event("input"));
  assert.equal(sendButton.disabled, false);
  sendButton.dispatchEvent(new Event("click"));
  await settle();
  const send = requests.find(
    (request) => request.function === "session_control.message.send",
  );
  assert.deepEqual(send.payload.selector, preview.payload.selector);
  assert.equal(send.payload.confirmation_token, "confirmed-filtered-roster");
  assert.equal(send.payload.body, "Inspect the current roster audience.");
  assert.ok(send.payload.idempotency_key.startsWith("workbench-message:"));
  mounted.unmount();
});

test("a card Message action sends to only that session", async (t) => {
  const requests = [];
  const rows = [
    sessionRow("session-one", "active", {
      latest_message: {
        message_id: "latest-one",
        state: "acknowledged",
        created_at: "2026-08-27T11:59:00Z",
      },
    }),
    sessionRow("session-two", "active"),
  ];
  const handlers = {
    "session_control.message.preview": (request) => ok({
      recipients: [{ ...rows[0] }],
      recipient_count: 1,
      confirmation_token: "confirmed-one",
    }),
    "session_control.message.send": () => ok({
      message_id: "message-one", recipient_count: 1, recipients: [],
    }),
  };
  const { root, mounted } = await mountRoster(t, rows, requests, handlers);
  const card = byClass(root, "session-card")[0];
  const latest = byClass(card, "session-latest-message")[0];
  assert.deepEqual(
    latest.children.map((node) => [node.tagName, node.className]),
    [
      ["BUTTON", "item-button session-message-button has-tooltip"],
      ["SPAN", "session-latest-label"],
      ["SPAN", "session-message-badge is-acknowledged has-tooltip"],
    ],
  );
  assert.equal(latest.children[0].textContent, "Message");
  assert.equal(latest.children[1].textContent, "Latest:");
  assert.match(latest.children[2].textContent, /^acknowledged · /);
  assert.equal(byClass(card, "session-control-actions").length, 0);
  button(card, "Message").dispatchEvent(new Event("click"));
  await settle();
  const preview = requests.find(
    (request) => request.function === "session_control.message.preview",
  );
  assert.deepEqual(preview.payload.selector, { session_ids: ["session-one"] });
  assert.equal(byClass(root, "session-message-preview-list")[0].children.length, 1);

  const body = byClass(root, "session-message-body")[0];
  body.value = "Act on this one session.";
  body.dispatchEvent(new Event("input"));
  button(root, "Send message").dispatchEvent(new Event("click"));
  await settle();
  const send = requests.find(
    (request) => request.function === "session_control.message.send",
  );
  assert.deepEqual(send.payload.selector, { session_ids: ["session-one"] });
  mounted.unmount();
});

test("transparent audience resolution blocks an unroutable roster member", async (t) => {
  const requests = [];
  const rows = [sessionRow("blocked", "active", {
    messageability: { messageable: false, reason: "unknown_surface" },
  })];
  const handlers = {
    "session_control.message.preview": () => ok({
      recipients: rows,
      recipient_count: 1,
      confirmation_token: "confirmed-blocked",
    }),
  };
  const { root, mounted } = await mountRoster(t, rows, requests, handlers);
  button(root, "Message all").dispatchEvent(new Event("click"));
  await settle();
  const body = byClass(root, "session-message-body")[0];
  body.value = "This must stay blocked.";
  body.dispatchEvent(new Event("input"));
  assert.equal(button(root, "Send message").disabled, true);
  assert.ok(byClass(root, "session-control-status").at(-1).textContent.includes(
    "1 session cannot receive Fleet messages",
  ));
  assert.equal(
    requests.some((request) => request.function === "session_control.message.send"),
    false,
  );
  mounted.unmount();
});
