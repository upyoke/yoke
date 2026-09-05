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
  messageRow,
  ok,
  renderInbox,
  requestRow,
} from "./universe_ui_inbox_test_support.mjs";

test("Inbox renders the two content types and their served counts", async () => {
  const { client, main } = renderInbox(["10"]);
  await settle();

  const headings = allNodes(main)
    .filter((node) => node.tagName === "H2")
    .map(ownTextContent);
  assert.deepEqual(headings, ["Needs your decision", "Messages"]);
  assert.equal(byClass(main, "inbox-row").length, 2);
  assert.deepEqual(
    byClass(main, "panel-count").map((node) => node.textContent),
    ["· 1", "· 1"],
  );
  assert.equal(
    byClass(main, "inbox-panel-hint")[0].textContent,
    "the gate waits until you resolve",
  );
  assert.deepEqual(client.requests[0], {
    function: "inbox.list", payload: { project_ids: [10] },
  });
  assert.deepEqual(
    byClass(main, "inbox-row-subtitle")[0].children
      .filter((node) => node.tagName === "SPAN")
      .map((node) => node.textContent),
    [
      "dash v3 · approval_defaults.reviewing-implementation",
      " · ",
      "requested ",
      " · ",
      "you: project owner",
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
  assert.equal(byClass(main, "inbox-row").length, 1);
  assert.equal(byClass(main, "inbox-empty")[0].textContent,
    "Nothing is waiting on you.");
});

test("request changes collects the required note before resolving", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "inbox.list") {
        return ok({
          needs_decision: [requestRow({
            actions: ["approve", "request_changes"],
          })],
          messages: [],
          pending_actor_message_count: 0,
        });
      }
      return ok({ request: { id: request.payload.request_id } });
    },
  };
  renderInboxView({
    document: documentNode,
    client,
    isMounted: () => true,
  }, main, "all");
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
  assert.equal(requests.filter(
    (request) => request.function === "decision_requests.resolve",
  ).length, 0);

  note.value = "Name the missing evidence.";
  send.dispatchEvent(new Event("click"));
  await settle();
  const resolve = requests.find(
    (request) => request.function === "decision_requests.resolve",
  );
  assert.deepEqual(resolve.payload, {
    request_id: 7,
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
          messages: [],
          pending_actor_message_count: 0,
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

test("acknowledging a message clears it from the served list", async () => {
  const { client, main } = renderInbox();
  await settle();
  byClass(main, "inbox-read")
    .find((node) => node.textContent === "Acknowledge")
    .dispatchEvent(new Event("click"));
  await settle();

  assert.ok(client.requests.some(
    (request) => request.function === "session_control.message.acknowledge"
      && request.payload.message_id === "msg-19",
  ));
  assert.equal(byClass(main, "inbox-empty").at(-1).textContent,
    "No unread messages.");
});

test("message acknowledgement failures stay visible and retryable", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = {
    async call(request) {
      if (request.function === "inbox.list") {
        return ok({
          needs_decision: [],
          messages: [messageRow()],
          pending_actor_message_count: 1,
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

  const acknowledge = byClass(main, "inbox-read").find(
    (node) => node.textContent === "Acknowledge",
  );
  acknowledge.dispatchEvent(new Event("click"));
  await settle();
  assert.match(
    byClass(main, "inbox-row-error")[0].textContent,
    /session_control\.message\.acknowledge unavailable/,
  );
  assert.equal(acknowledge.disabled, false);
});

test("all four request kinds link to their one subject home", () => {
  const cases = [
    ["deployment_stage_approval", "deployment_stage", {}, "#/deployments?project=10"],
    [
      "qa_needs_review",
      "qa_requirement",
      { plan_id: 7, case_name: "checkout-flow" },
      "#/qa-plans/7?project=10",
    ],
    ["lifecycle_transition_approval", "item_transition", { item_ref: "YOK-7" }, "#/items/7?project=10"],
    ["machine_approval", "machine_auth_request", {}, "#/machines"],
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
  })), "#/qa-activity?project=10");
  assert.equal(inboxPresentation.subjectHref(requestRow({
    subject_context: { item_id: 2262 },
  })), "#/items?project=10");
});


test("an every-approver gate shows progress and reports the viewer's own decision",
  async () => {
    const { main } = renderInbox("all", [requestRow({
      approval_progress: {
        mode: "all",
        required: 2,
        satisfied: 1,
        outstanding: ["Bo"],
        resolved: false,
      },
      decided_by_you: true,
      your_decision: { actor_id: 2, action: "approve" },
    })]);
    await settle();
    const subtitle = byClass(main, "inbox-row-subtitle")[0].textContent;
    assert.ok(subtitle.includes("1 of 2, waiting on Bo"), subtitle);
    assert.ok(subtitle.includes("you chose Approve"), subtitle);
    assert.equal(byClass(main, "inbox-action").length, 0);
    assert.equal(
      byClass(main, "inbox-decided")[0].textContent,
      "you chose Approve",
    );
  },
);


test("a single-approver gate keeps its actions and shows no progress count",
  async () => {
    const { main } = renderInbox("all", [requestRow({
      approval_progress: {
        mode: "any",
        required: 1,
        satisfied: 0,
        outstanding: ["project owner"],
        resolved: false,
      },
      decided_by_you: false,
    })]);
    await settle();
    const subtitle = byClass(main, "inbox-row-subtitle")[0].textContent;
    assert.ok(!subtitle.includes(" of "), subtitle);
    assert.deepEqual(
      byClass(main, "inbox-action").map((node) => node.textContent),
      ["Reject", "Approve"],
    );
  },
);
