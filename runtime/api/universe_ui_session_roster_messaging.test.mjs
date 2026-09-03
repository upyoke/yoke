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
    executor: "codex",
    executor_surface: "codex-cli",
    model: "gpt-5.6-sol",
    execution_lane: "ALTMAN",
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
  documentNode.defaultView.location.hash = "#/sessions?project=1";
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "sessions.list") {
        return ok({
          rows: rows.filter((row) => row.liveness === request.payload.liveness),
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

test("roster defaults to active and exposes only the supported filters", async (t) => {
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
    fields.map((field) => field.children[0].textContent),
    ["Search", "Harness", "Machine", "State"],
  );
  const state = fields.at(-1).children[1];
  assert.equal(state.value, "active");
  assert.deepEqual(
    state.children.map((entry) => [entry.value, entry.textContent]),
    [["", "Any state"], ["active", "Active"], ["ended", "Ended"]],
  );
  assert.deepEqual(cardIds(root), ["active-codex", "stale-cursor"]);
  const staleCard = byClass(root, "session-card").find(
    (card) => card.getAttribute("data-session-id") === "stale-cursor",
  );
  assert.equal(staleCard.classList.contains("is-stale"), true);
  assert.deepEqual(
    byClass(staleCard, "session-stale-pill").map(
      (pill) => [pill.textContent, pill.className],
    ),
    [["stale", "pill crit session-stale-pill"]],
  );
  assert.deepEqual(
    requests.filter((request) => request.function === "sessions.list")
      .map((request) => request.payload.liveness),
    ["active", "stale", "ended"],
  );

  state.value = "";
  state.dispatchEvent(new Event("change"));
  assert.deepEqual(
    cardIds(root), ["active-codex", "stale-cursor", "ended-cursor"],
  );
  const anyStaleCard = byClass(root, "session-card").find(
    (card) => card.getAttribute("data-session-id") === "stale-cursor",
  );
  assert.equal(anyStaleCard.classList.contains("is-stale"), true);
  assert.equal(byClass(anyStaleCard, "session-stale-pill").length, 1);
  state.value = "ended";
  state.dispatchEvent(new Event("change"));
  assert.deepEqual(cardIds(root), ["ended-cursor"]);
  state.value = "";
  state.dispatchEvent(new Event("change"));
  const harness = fields.find(
    (field) => field.children[0].textContent === "Harness",
  ).children[1];
  harness.value = "cursor";
  harness.dispatchEvent(new Event("input"));
  assert.deepEqual(cardIds(root), ["stale-cursor", "ended-cursor"]);
  assert.equal(button(root, "Message all").title, "Message all 2 shown sessions");

  button(root, "Clear filters").dispatchEvent(new Event("click"));
  assert.equal(state.value, "active");
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
  const state = fields.at(-1).children[1];
  const harness = fields.find(
    (field) => field.children[0].textContent === "Harness",
  ).children[1];
  state.value = "";
  state.dispatchEvent(new Event("change"));
  harness.value = "cursor";
  harness.dispatchEvent(new Event("input"));

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
    "Filters: State: any · Harness: cursor",
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
      ["BUTTON", "item-button session-message-button"],
      ["SPAN", "session-latest-label"],
      ["SPAN", "session-message-badge is-acknowledged"],
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
