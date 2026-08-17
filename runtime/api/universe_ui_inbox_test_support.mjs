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
    blocking: true,
    created_at: "2026-07-26T12:00:00Z",
    asked_of_you: false,
    authority_reason: "project owner",
    actions: ["approve", "reject"],
    ...overrides,
  };
}

export function notificationRow(overrides = {}) {
  return {
    id: 19,
    event_id: "event-19",
    notification_kind: "deployment_run_completed",
    reason: "run completed",
    created_at: "2026-07-26T13:00:00Z",
    event_name: "DeploymentRunSucceeded",
    project_id: 10,
    event_outcome: "completed",
    event: {
      context: {
        target_environment: "Production",
        run_id: "run-20260726-019",
      },
    },
    ...overrides,
  };
}

export function inboxClient() {
  const requests = [];
  let needs = [requestRow()];
  let reviews = [requestRow({
    id: 8,
    kind: "strategy_revision_review",
    subject_type: "strategy_doc_revision",
    subject_key: "10:WORKFLOW-TYPES:7",
    subject_context: {
      slug: "WORKFLOW-TYPES",
      revision: 7,
      author_label: "Dana",
    },
    blocking: false,
    asked_of_you: true,
    authority_reason: "asked of you",
    actions: ["approve", "request_changes"],
  })];
  let notifications = [notificationRow()];
  return {
    requests,
    async call(request) {
      requests.push(structuredClone(request));
      if (request.function === "inbox.list") {
        return ok({
          needs_decision: structuredClone(needs),
          requests: structuredClone(reviews),
          notifications: structuredClone(notifications),
        });
      }
      if (request.function === "decision_requests.resolve") {
        needs = needs.filter((row) => row.id !== request.payload.request_id);
        reviews = reviews.filter((row) => row.id !== request.payload.request_id);
        return ok({ request: { id: request.payload.request_id, status: "resolved" } });
      }
      if (request.function === "notifications.read") {
        notifications = notifications.filter(
          (row) => row.id !== request.payload.notification_id,
        );
        return ok({ read: true, notification_id: request.payload.notification_id });
      }
      if (request.function === "notifications.read_all") {
        const count = notifications.length;
        notifications = [];
        return ok({ read: count > 0, count });
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
