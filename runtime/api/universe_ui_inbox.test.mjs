import assert from "node:assert/strict";
import test from "node:test";

import {
  inboxPresentation,
  renderInboxView,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({
  status: 200, envelope: { success: true, result },
});

function requestRow(overrides = {}) {
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

function notificationRow(overrides = {}) {
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
        target_env: "Production",
        run_id: "run-20260726-019",
      },
    },
    ...overrides,
  };
}

function inboxClient() {
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

function render(scope = "all") {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = inboxClient();
  renderInboxView({
    document: documentNode,
    client,
    isMounted: () => true,
  }, main, scope);
  return { client, main };
}

test("Inbox matches the three-class prototype and renders served counts", async () => {
  const { client, main } = render(["10"]);
  await settle();

  const headings = allNodes(main)
    .filter((node) => node.tagName === "H2")
    .map((node) => node.textContent);
  assert.deepEqual(headings, [
    "Needs your decision", "Requests", "Notifications",
  ]);
  assert.equal(byClass(main, "inbox-row").length, 3);
  assert.deepEqual(
    byClass(main, "panel-count").map((node) => node.textContent),
    ["· 1", "· 1", "· 1"],
  );
  assert.equal(
    byClass(main, "inbox-panel-hint")[0].textContent,
    "the gate waits until you resolve",
  );
  assert.deepEqual(client.requests[0], {
    function: "inbox.list", payload: { project_ids: [10] },
  });
  const asked = byClass(main, "inbox-addressed");
  assert.equal(asked.length, 1);
  assert.equal(asked[0].textContent, "asked of you");
});

test("decision buttons call engine actions and refresh the instance lists", async () => {
  const { client, main } = render();
  await settle();
  const approve = allNodes(main).find(
    (node) => node.attributes.get("data-action") === "approve"
      && node.parentNode.parentNode.attributes.get("data-request-id") === "7",
  );
  approve.dispatchEvent(new Event("click"));
  await settle();

  const resolve = client.requests.find(
    (request) => request.function === "decision_requests.resolve",
  );
  assert.deepEqual(resolve.payload, { request_id: 7, action: "approve" });
  assert.equal(byClass(main, "inbox-row").length, 2);
  assert.equal(byClass(main, "inbox-empty")[0].textContent,
    "Nothing is waiting on you.");
});

test("request changes collects the required note before resolving", async () => {
  const { client, main } = render();
  await settle();
  const requestChanges = allNodes(main).find(
    (node) => node.attributes.get("data-action") === "request_changes",
  );
  requestChanges.dispatchEvent(new Event("click"));
  const note = byClass(main, "inbox-note")[0];
  assert.ok(note);
  const send = byClass(main, "inbox-note-composer")[0].children[2];
  send.dispatchEvent(new Event("click"));
  assert.ok(note.classList.contains("invalid"));
  assert.equal(client.requests.filter(
    (request) => request.function === "decision_requests.resolve",
  ).length, 0);

  note.value = "Name the missing evidence.";
  send.dispatchEvent(new Event("click"));
  await settle();
  const resolve = client.requests.find(
    (request) => request.function === "decision_requests.resolve",
  );
  assert.deepEqual(resolve.payload, {
    request_id: 8,
    action: "request_changes",
    note: "Name the missing evidence.",
  });
});

test("notification actions are actor-read mutations, including mark all", async () => {
  const first = render();
  await settle();
  byClass(first.main, "inbox-read")
    .find((node) => node.textContent === "Mark read")
    .dispatchEvent(new Event("click"));
  await settle();
  assert.ok(first.client.requests.some(
    (request) => request.function === "notifications.read"
      && request.payload.notification_id === 19,
  ));
  assert.equal(byClass(first.main, "inbox-empty").at(-1).textContent,
    "Nothing new.");

  const second = render();
  await settle();
  byClass(second.main, "inbox-read-all")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.ok(second.client.requests.some(
    (request) => request.function === "notifications.read_all",
  ));
});

test("all five request kinds link to their one subject home", () => {
  const cases = [
    ["deployment_stage_approval", "deployment_stage", {}, "#/delivery/runs?project=10"],
    ["qa_needs_review", "qa_requirement", {}, "#/qa?project=10"],
    ["lifecycle_transition_approval", "item_transition", { item_id: 7 }, "#/items/7?project=10"],
    ["machine_approval", "machine_auth_request", {}, "#/access"],
    ["strategy_revision_review", "strategy_doc_revision", { slug: "PLAN" }, "#/strategy/PLAN?project=10"],
  ];
  for (const [kind, subjectType, subjectContext, expected] of cases) {
    assert.equal(inboxPresentation.subjectHref(requestRow({
      kind, subject_type: subjectType, subject_context: subjectContext,
    })), expected);
  }
});
