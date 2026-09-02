import assert from "node:assert/strict";
import test from "node:test";

import { renderSessionMessagesView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_messages.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function sessionMessage(messageId, state, overrides = {}) {
  return {
    message_id: messageId,
    body: `Body for ${messageId}`,
    created_at: "2026-09-02T12:00:00Z",
    sender_actor_id: 2,
    sender_actor_label: "Ben",
    sender_actor_kind: "human",
    sender_session_id: null,
    sender_surface: "web_form",
    sender_surface_label: "dashboard",
    cancelled_at: null,
    recipients: [{
      session_id: `session-${messageId}`,
      project_id: 1,
      state,
      created_at: "2026-09-02T12:00:00Z",
      cancelled_at: state === "cancelled" ? "2026-09-02T12:01:00Z" : null,
    }],
    ...overrides,
  };
}

function renderMessages(messages, onCall = () => {}) {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = {
    async call(request) {
      onCall(request);
      if (request.function === "session_control.message.list") {
        return ok({ messages: structuredClone(messages), count: messages.length });
      }
      if (request.function === "sessions.list") return ok({ rows: [] });
      if (request.function === "session_control.message.cancel") {
        const message = messages.find(
          (candidate) => candidate.message_id === request.payload.message_id,
        );
        message.cancelled_at = "2026-09-02T12:02:00Z";
        message.recipients[0].state = "cancelled";
        message.recipients[0].cancelled_at = message.cancelled_at;
        return ok({ message: structuredClone(message) });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  renderSessionMessagesView({
    document: documentNode,
    client,
    isMounted: () => true,
    projects: () => [],
  }, main, "all");
  return main;
}

function messageCardIds(root) {
  return byClass(root, "session-message-card").map(
    (card) => card.getAttribute("data-message-id"),
  );
}

test("recipient cancellation renders a terminal non-attention summary", async () => {
  const message = sessionMessage("cancelled-recipient", "cancelled");
  const main = renderMessages([message]);
  await settle();

  const [card] = byClass(main, "session-message-card");
  assert.equal(message.cancelled_at, null);
  assert.equal(card.getAttribute("data-message-state"), "cancelled");
  assert.equal(card.className.includes("is-attention"), false);
  assert.ok(allNodes(card).some((node) => node.textContent === "Cancelled"));
  assert.equal(allNodes(card).some(
    (node) => node.tagName === "BUTTON" && node.textContent === "Cancel",
  ), false);
});

test("cancelling a message preserves its position after the list reloads", async () => {
  const requests = [];
  const messages = [
    sessionMessage("acted-on", "pending"),
    sessionMessage("still-awaiting", "pending"),
  ];
  const main = renderMessages(messages, (request) => requests.push(request));
  await settle();
  assert.deepEqual(messageCardIds(main), ["acted-on", "still-awaiting"]);

  const actedOn = byClass(main, "session-message-card")[0];
  allNodes(actedOn).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Cancel",
  ).dispatchEvent(new Event("click"));
  await settle();

  assert.ok(requests.some(
    (request) => request.function === "session_control.message.cancel",
  ));
  assert.deepEqual(messageCardIds(main), ["acted-on", "still-awaiting"]);
  assert.equal(
    byClass(main, "session-message-card")[0].getAttribute("data-message-state"),
    "cancelled",
  );
});
