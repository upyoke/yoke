// Delivery notices report; they ask for nothing. The Inbox keeps them apart
// from the decisions that do ask and from the messages a person sent, and
// names which of the two notices each one is.

import assert from "node:assert/strict";
import test from "node:test";

import {
  renderInboxView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  inboxSection as section,
  messageRow,
  ok,
} from "./universe_ui_inbox_test_support.mjs";

function renderWith(messages) {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  renderInboxView({
    document: documentNode,
    isMounted: () => true,
    projects: () => [{ id: 10, slug: "yoke", name: "Yoke" }],
    client: {
      async call(request) {
        requests.push(request);
        if (request.function === "inbox.list") {
          return ok({
            needs_decision: [],
            messages,
            pending_actor_message_count: messages.length,
          });
        }
        if (request.function === "session_control.message.acknowledge") {
          return ok({ acknowledged: true });
        }
        throw new Error(`unexpected function ${request.function}`);
      },
    },
  }, main, "all");
  return { main, requests };
}

test("QA-result and item-done notices are separate rows in their own section", async () => {
  const { main } = renderWith([
    messageRow({
      message_id: "msg-qa",
      notice_kind: "qa_result",
      body: "Deployment run run-20260726-001 QA stage 'item-qa' passed.",
    }),
    messageRow({
      message_id: "msg-done",
      notice_kind: "delivery_done",
      body: "YOK-2228 is done. Delivery completed to prod.",
    }),
    messageRow({ message_id: "msg-peer", body: "Stage deploy is red." }),
  ]);
  await settle();

  const notices = section(main, "notices");
  assert.equal(notices.hidden, false);
  // Two distinct events, each named — a retry of one must not read as the
  // other arriving.
  assert.deepEqual(
    byClass(notices, "inbox-notice-kind").map((node) => node.textContent),
    ["QA result", "Item done"],
  );
  // What clears an informational row is a dismissal, not an answer.
  assert.deepEqual(
    byClass(notices, "inbox-read").map((node) => node.textContent),
    ["Dismiss", "Dismiss"],
  );
  assert.deepEqual(
    byClass(notices, "inbox-message-meta").map(
      (node) => node.children[0].textContent,
    ),
    ["Informational", "Informational"],
  );

  // The peer message stays where a person's message belongs, with the
  // control that says an answer may be expected.
  const messages = section(main, "messages");
  assert.equal(byClass(messages, "inbox-message").length, 1);
  assert.equal(byClass(messages, "inbox-notice-kind").length, 0);
  assert.equal(byClass(messages, "inbox-read")[0].textContent, "Acknowledge");
});

test("no notice means no notices section, and the counts stay separate", async () => {
  const { main } = renderWith([messageRow({ message_id: "msg-peer" })]);
  await settle();

  assert.equal(section(main, "notices").hidden, true);
  assert.equal(
    byClass(section(main, "notices"), "overview-section-count")[0].textContent, "0",
  );
  assert.equal(
    byClass(section(main, "messages"), "overview-section-count")[0].textContent, "1",
  );
});
