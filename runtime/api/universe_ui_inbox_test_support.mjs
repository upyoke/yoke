import { renderInboxView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";
import { FakeDocument } from "./universe_ui_dom_test_support.mjs";

export const ok = (result) => ({
  status: 200, envelope: { success: true, result },
});

export function requestRow(overrides = {}) {
  return {
    id: 7,
    kind: "lifecycle_transition_approval",
    subject_type: "item_transition",
    subject_key: "1907:reviewing-implementation",
    subject_context: {
      item_id: 1907,
      item_ref: "YOK-1907",
      transition: "reviewing-implementation",
      policy_summary: "Issue v1 approval policy",
      title: "YOK-1907 — approve the reviewing-implementation transition",
    },
    project_id: 10,
    created_at: "2026-07-26T12:00:00Z",
    asked_of_you: false,
    authority_reason: "project owner",
    actions: ["approve", "reject"],
    ...overrides,
  };
}

export function messageRow(overrides = {}) {
  return {
    message_id: "msg-19",
    body: "Stage deploy is red on the release gate.",
    created_at: "2026-07-26T13:00:00Z",
    project_id: 10,
    actor_receipt: { state: "pending" },
    ...overrides,
  };
}

export function inboxClient() {
  const requests = [];
  let needs = [requestRow()];
  let messages = [messageRow()];
  return {
    requests,
    async call(request) {
      requests.push(structuredClone(request));
      if (request.function === "inbox.list") {
        return ok({
          needs_decision: structuredClone(needs),
          messages: structuredClone(messages),
          pending_actor_message_count: messages.length,
        });
      }
      if (request.function === "decision_requests.resolve") {
        needs = needs.filter((row) => row.id !== request.payload.request_id);
        return ok({ request: { id: request.payload.request_id, status: "resolved" } });
      }
      if (request.function === "session_control.message.acknowledge") {
        messages = messages.filter(
          (row) => row.message_id !== request.payload.message_id,
        );
        return ok({ acknowledged: true, message_id: request.payload.message_id });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

export function renderInbox(scope = "all") {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = inboxClient();
  renderInboxView({
    document: documentNode,
    client,
    isMounted: () => true,
    projects: () => [{ id: 10, slug: "yoke", name: "Yoke" }],
  }, main, scope);
  return { client, main };
}
