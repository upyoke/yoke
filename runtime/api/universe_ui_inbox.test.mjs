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
  ownTextContent,
  settle,
} from "./universe_ui_dom_test_support.mjs";

import {
  notificationRow,
  ok,
  renderInbox,
  requestRow,
} from "./universe_ui_inbox_test_support.mjs";

test("Inbox matches the three-class prototype and renders served counts", async () => {
  const { client, main } = renderInbox(["10"]);
  await settle();

  const headings = allNodes(main)
    .filter((node) => node.tagName === "H2")
    .map(ownTextContent);
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
  assert.equal(byClass(main, "inbox-addressed").length, 0);
  assert.match(
    allNodes(main).map((node) => node.textContent || "").join(" "),
    /asked of you/,
  );
  assert.equal(allNodes(main).filter((node) => node.tagName === "TIME").length, 3);
  assert.deepEqual(
    byClass(main, "inbox-row-subtitle")[0].children
      .filter((node) => node.tagName === "SPAN")
      .map((node) => node.textContent),
    [
      "Issue v1 approval policy",
      " · ",
      "requested ",
      " · ",
      "you: project owner",
    ],
  );
  assert.deepEqual(
    byClass(main, "inbox-row-subtitle")[1].children
      .filter((node) => node.tagName === "SPAN")
      .map((node) => node.textContent),
    [
      "revision by Dana",
      " · ",
      " · ",
      "the doc stays live while this waits · asked of you",
    ],
  );
  assert.ok(byClass(main, "inbox-action").every(
    (node) => node.classList.contains("item-button"),
  ));
  const firstRow = byClass(main, "inbox-row")[0];
  assert.deepEqual(
    byClass(firstRow, "inbox-action").map((node) => node.textContent),
    ["Reject", "Approve"],
  );
  assert.deepEqual(
    byClass(main, "inbox-row")[1].children.at(-1).children.map(
      (node) => node.textContent,
    ),
    ["Request changes", "Approve"],
  );
  assert.equal(firstRow.attributes.get("role"), "link");
  firstRow.dispatchEvent(new Event("click"));
  assert.equal(
    main.ownerDocument.defaultView.location.hash,
    "#/items/1907?project=10",
  );
});

test("decision buttons call engine actions and refresh the instance lists", async () => {
  const { client, main } = renderInbox();
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
  const { client, main } = renderInbox();
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

test("resolving a decision disables every action on that row", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  let finishResolve;
  const client = {
    async call(request) {
      if (request.function === "inbox.list") {
        return ok({
          needs_decision: [requestRow()],
          requests: [],
          notifications: [],
        });
      }
      if (request.function === "decision_requests.resolve") {
        return new Promise((resolve) => { finishResolve = resolve; });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
  renderInboxView({
    document: documentNode,
    client,
    isMounted: () => true,
  }, main, "all");
  await settle();

  const actions = byClass(byClass(main, "inbox-row")[0], "inbox-action");
  actions[0].dispatchEvent(new Event("click"));
  assert.ok(actions.every((node) => node.disabled));
  finishResolve({
    status: 500,
    envelope: { success: false, error: { message: "try again" } },
  });
  await settle();
  assert.ok(actions.every((node) => !node.disabled));
  assert.equal(byClass(main, "inbox-row-error")[0].textContent, "try again");
});

test("notification actions are actor-read mutations, including mark all", async () => {
  const first = renderInbox();
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

  const second = renderInbox(["10"]);
  await settle();
  byClass(second.main, "inbox-read-all")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(second.client.requests.find(
    (request) => request.function === "notifications.read_all",
  ), {
    function: "notifications.read_all",
    payload: { project_ids: [10] },
  });

  const global = renderInbox();
  await settle();
  byClass(global.main, "inbox-read-all")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(global.client.requests.find(
    (request) => request.function === "notifications.read_all",
  ), { function: "notifications.read_all", payload: {} });
});

test("notification mutation failures stay visible and retryable", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = {
    async call(request) {
      if (request.function === "inbox.list") {
        return ok({
          needs_decision: [],
          requests: [],
          notifications: [notificationRow()],
        });
      }
      return {
        status: 503,
        envelope: {
          success: false,
          error: { message: `${request.function} unavailable` },
        },
      };
    },
  };
  renderInboxView({
    document: documentNode,
    client,
    isMounted: () => true,
  }, main, "all");
  await settle();

  byClass(main, "inbox-read").find(
    (node) => node.textContent === "Mark read",
  ).dispatchEvent(new Event("click"));
  await settle();
  assert.match(
    byClass(main, "inbox-row-error")[0].textContent,
    /notifications\.read unavailable/,
  );
  assert.equal(
    byClass(main, "inbox-read").find(
      (node) => node.textContent === "Mark read",
    ).disabled,
    false,
  );

  byClass(main, "inbox-read-all")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.match(
    byClass(main, "inbox-panel-error")[0].textContent,
    /notifications\.read_all unavailable/,
  );
  assert.equal(byClass(main, "inbox-read-all")[0].disabled, false);
});

test("all five request kinds link to their one subject home", () => {
  const cases = [
    ["deployment_stage_approval", "deployment_stage", {}, "#/delivery/runs?project=10"],
    [
      "qa_needs_review",
      "qa_requirement",
      { plan_id: 7, case_name: "checkout-flow" },
      "#/qa/plans/7?project=10",
    ],
    ["lifecycle_transition_approval", "item_transition", { item_ref: "YOK-7" }, "#/items/7?project=10"],
    ["machine_approval", "machine_auth_request", {}, "#/access"],
    ["strategy_revision_review", "strategy_doc_revision", { slug: "PLAN" }, "#/strategy/PLAN?project=10"],
  ];
  for (const [kind, subjectType, subjectContext, expected] of cases) {
    assert.equal(inboxPresentation.subjectHref(requestRow({
      kind, subject_type: subjectType, subject_context: subjectContext,
    })), expected);
  }
  assert.equal(inboxPresentation.subjectHref(requestRow({
    kind: "qa_needs_review",
    subject_type: "qa_requirement",
    subject_context: {},
  })), "#/qa/activity?project=10");
  assert.equal(inboxPresentation.subjectHref(requestRow({
    subject_context: { item_id: 2262 },
  })), "#/items?project=10");
});

test("notifications link their full row to the subject home", () => {
  assert.equal(
    inboxPresentation.notificationHref(notificationRow()),
    "#/delivery/runs?project=10",
  );
  assert.equal(
    inboxPresentation.notificationHref(notificationRow({
      notification_kind: "item_block_state_changed",
      event: { context: { item_ref: "YOK-1907" } },
    })),
    "#/items/1907?project=10",
  );
});

test("decision notifications use the served kind and action without inventing subject facts", () => {
  assert.deepEqual(
    inboxPresentation.notificationPresentation(notificationRow({
      notification_kind: "decision_request_resolved",
      reason: "deployment_stage_approval approve",
      event: {
        context: {
          request_id: 12,
          kind: "deployment_stage_approval",
          action: "approve",
          resolution_actor_label: "ben",
        },
      },
    })),
    {
      title: "Your stage approval was resolved",
      subtitle: "approved by ben",
    },
  );
  assert.deepEqual(
    inboxPresentation.notificationPresentation(notificationRow({
      notification_kind: "decision_request_resolved",
      reason: "strategy_revision_review request_changes",
      event: {
        context: {
          request_id: 13,
          kind: "strategy_revision_review",
          action: "request_changes",
        },
      },
    })),
    {
      title: "Your decision request was resolved",
      subtitle: "changes requested",
    },
  );
});
