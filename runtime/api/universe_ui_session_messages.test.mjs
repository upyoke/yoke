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
    needs_attention: ["pending", "injected"].includes(state),
    ...overrides,
  };
}

function renderMessages(messages, onCall = () => {}, options = {}) {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  let listCall = 0;
  const client = {
    async call(request) {
      onCall(request);
      if (request.function === "session_control.message.list") {
        const page = options.pages?.[listCall] || {
          messages,
          next_cursor: null,
        };
        listCall += 1;
        return ok({
          messages: structuredClone(page.messages),
          count: page.messages.length,
          actionable_count: messages.filter((row) => row.needs_attention).length,
          settled_matched_count: messages.filter((row) => !row.needs_attention).length,
          next_cursor: page.next_cursor,
        });
      }
      if (request.function === "session_control.message.get") {
        const message = messages.find(
          (candidate) => candidate.message_id === request.payload.message_id,
        );
        return ok({ message: structuredClone(message) });
      }
      if (request.function === "session_control.message.cancel") {
        const message = messages.find(
          (candidate) => candidate.message_id === request.payload.message_id,
        );
        message.cancelled_at = "2026-09-02T12:02:00Z";
        message.recipients[0].state = "cancelled";
        message.recipients[0].cancelled_at = message.cancelled_at;
        message.needs_attention = false;
        return ok({ message: structuredClone(message) });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  renderSessionMessagesView({
    document: documentNode,
    client,
    isMounted: () => true,
    projects: () => options.projects || [],
  }, main, options.scope || "all");
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
  const initialOrder = messageCardIds(main);
  assert.deepEqual(initialOrder, ["still-awaiting", "acted-on"]);

  const actedOn = byClass(main, "session-message-card").find(
    (card) => card.getAttribute("data-message-id") === "acted-on",
  );
  allNodes(actedOn).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Cancel",
  ).dispatchEvent(new Event("click"));
  await settle();

  assert.ok(requests.some(
    (request) => request.function === "session_control.message.cancel",
  ));
  assert.deepEqual(messageCardIds(main), initialOrder);
  assert.equal(
    byClass(main, "session-message-card").find(
      (card) => card.getAttribute("data-message-id") === "acted-on",
    ).getAttribute("data-message-state"),
    "cancelled",
  );
});

test("selected projects are sent before the server applies its page window", async () => {
  const requests = [];
  renderMessages(
    [sessionMessage("selected", "pending")],
    (request) => requests.push(request),
    { scope: [2], projects: [{ id: 1 }, { id: 2 }] },
  );
  await settle();

  const list = requests.find(
    (request) => request.function === "session_control.message.list",
  );
  assert.deepEqual(list.payload.projects, ["2"]);
  assert.equal("limit" in list.payload, false);
});

test("settled history loads the next cursor without repeating compact rows", async () => {
  const requests = [];
  const messages = Array.from(
    { length: 55 },
    (_value, index) => sessionMessage(`settled-${index}`, "acknowledged"),
  );
  const main = renderMessages(
    messages,
    (request) => requests.push(request),
    {
      pages: [
        { messages: messages.slice(0, 50), next_cursor: "cursor-1" },
        { messages: messages.slice(50), next_cursor: null },
      ],
    },
  );
  await settle();
  assert.equal(messageCardIds(main).length, 50);

  allNodes(main).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Load more",
  ).dispatchEvent(new Event("click"));
  await settle();

  assert.equal(messageCardIds(main).length, 55);
  assert.equal(requests[1].payload.cursor, "cursor-1");
  assert.equal(allNodes(main).some(
    (node) => node.tagName === "BUTTON" && node.textContent === "Load more",
  ), false);
});

test("full receipt and relay detail is fetched only when a row expands", async () => {
  const requests = [];
  const main = renderMessages(
    [sessionMessage("expand", "pending")],
    (request) => requests.push(request),
  );
  await settle();
  assert.deepEqual(
    requests.map((request) => request.function),
    ["session_control.message.list"],
  );

  allNodes(main).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Details",
  ).dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(
    requests.map((request) => request.function),
    ["session_control.message.list", "session_control.message.get"],
  );
  assert.ok(byClass(main, "session-message-recipients").length);
});
