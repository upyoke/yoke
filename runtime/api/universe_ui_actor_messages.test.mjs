import assert from "node:assert/strict";
import test from "node:test";

import { renderInboxView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";
import { renderSessionMessagesView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_messages.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { ok } from "./universe_ui_inbox_test_support.mjs";

function actorMessage() {
  return {
    message_id: "33333333-3333-4333-8333-333333333333",
    body: "Please review the result.",
    created_at: "2026-08-22T16:00:00Z",
    sender_actor_id: 10,
    sender_actor_label: "ben",
    sender_actor_kind: "human",
    sender_session_id: null,
    sender_surface: "web_form",
    sender_surface_label: "dashboard",
    actor_receipt: { actor_id: 11, state: "pending" },
  };
}

test("Inbox badges human messages and acknowledges through the shared receipt", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  let messages = [actorMessage()];
  const client = {
    async call(request) {
      requests.push(structuredClone(request));
      if (request.function === "inbox.list") {
        return ok({
          needs_decision: [],
          requests: [],
          notifications: [],
          messages: structuredClone(messages),
          pending_actor_message_count: messages.length,
        });
      }
      if (request.function === "session_control.message.acknowledge") {
        messages = [];
        return ok({ message: actorMessage() });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  renderInboxView({
    document: documentNode,
    client,
    isMounted: () => true,
    projects: () => [],
  }, main, "all");
  await settle();

  assert.equal(byClass(main, "inbox-message-row").length, 1);
  assert.match(byClass(main, "inbox-message-row")[0].textContent, /ben \(human, dashboard\)/);
  assert.equal(byClass(main, "panel-count")[2].textContent, "· 1");
  byClass(main, "inbox-read").find(
    (button) => button.textContent === "Acknowledge",
  ).dispatchEvent(new Event("click"));
  await settle();

  assert.deepEqual(requests.find(
    (request) => request.function === "session_control.message.acknowledge",
  ).payload, { message_id: "33333333-3333-4333-8333-333333333333" });
  assert.equal(byClass(main, "inbox-message-row").length, 0);
  assert.equal(byClass(main, "panel-count")[2].textContent, "· 0");
});

test("Messages tab badges and acknowledges the signed-in actor receipt", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  const message = {
    ...actorMessage(),
    actor_recipients: [{
      actor_id: 11,
      label: "reader",
      state: "pending",
      created_at: "2026-08-22T16:00:00Z",
    }],
    recipients: [],
  };
  const client = {
    async call(request) {
      requests.push(structuredClone(request));
      if (request.function === "session_control.message.list") {
        return ok({ messages: [structuredClone(message)], count: 1 });
      }
      if (request.function === "sessions.list") return ok({ rows: [] });
      if (request.function === "session_control.message.acknowledge") {
        message.actor_receipt.state = "read";
        message.actor_recipients[0].state = "read";
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
  await settle();

  assert.ok(allNodes(main).some((node) => node.textContent === "1 pending"));
  assert.match(byClass(main, "session-message-route")[0].textContent,
    /From ben \(human, dashboard\)/);
  allNodes(main).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Acknowledge",
  ).dispatchEvent(new Event("click"));
  await settle();

  assert.ok(requests.some(
    (request) => request.function === "session_control.message.acknowledge",
  ));
  assert.ok(allNodes(main).some((node) => node.textContent === "0 pending"));
  assert.equal(allNodes(main).filter(
    (node) => node.tagName === "BUTTON" && node.textContent === "Acknowledge",
  ).length, 0);
});
