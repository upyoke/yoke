import assert from "node:assert/strict";
import test from "node:test";

import { renderMachinesView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_machines.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  ownTextContent,
  settle,
} from "./universe_ui_dom_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });

function approvalRow(overrides = {}) {
  return {
    id: 42,
    kind: "machine_approval",
    subject_type: "machine_auth_request",
    subject_key: "5b234860-c927-46ab-b19a-9fb36df056aa",
    subject_context: {
      code: "WXYZ-1234",
      machine: "studio-mini",
      expires_at: "2026-09-04T12:10:00Z",
    },
    project_id: null,
    org_id: 1,
    created_at: "2026-09-04T12:00:00Z",
    originator_actor_id: 1,
    originator_actor_label: "dana",
    asked_of_you: false,
    authority_reason: "org admin",
    actions: ["approve", "deny"],
    ...overrides,
  };
}

function machinesClient(approvals) {
  const requests = [];
  let rows = [...approvals];
  return {
    requests,
    async call(request) {
      requests.push(structuredClone(request));
      if (request.function === "inbox.list") {
        return ok({
          needs_decision: [],
          machine_approvals: structuredClone(rows),
          messages: [],
          pending_actor_message_count: 0,
        });
      }
      if (request.function === "decision_requests.resolve") {
        rows = rows.filter((row) => row.id !== request.payload.request_id);
        return ok({
          request: { id: request.payload.request_id, status: "resolved" },
        });
      }
      // Relays and launches are not this test's subject. They render their
      // own unavailable state from this, which is what a real page does when
      // one composed read fails and the others do not.
      return {
        status: 503,
        envelope: { success: false, error: { message: "unavailable" } },
      };
    },
  };
}

function renderMachines(approvals) {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  const client = machinesClient(approvals);
  renderMachinesView({
    document: documentNode,
    client,
    isMounted: () => true,
    projects: () => [],
  }, main, "all", {});
  return { client, main, documentNode };
}

test("a pending machine approval is answered at the top of Machines", async () => {
  const { client, main } = renderMachines([approvalRow()]);
  await settle();

  const headings = allNodes(main)
    .filter((node) => node.tagName === "H2")
    .map(ownTextContent);
  assert.equal(headings[0], "Machines waiting for approval");
  assert.deepEqual(
    client.requests.filter((request) => request.function === "inbox.list"),
    [{ function: "inbox.list", payload: {} }],
  );

  const row = byClass(main, "inbox-row")[0];
  assert.equal(byClass(row, "inbox-row-title")[0].textContent, "Approve a new machine");
  const subtitle = byClass(row, "inbox-row-subtitle")[0].textContent;
  for (const fact of [
    "machine studio-mini",
    "one-time code WXYZ-1234",
    "requested by dana",
  ]) assert.ok(subtitle.includes(fact), `${fact} in ${subtitle}`);

  // Deny before Approve: the reversible answer never sits under the cursor
  // of the one that admits a machine.
  const actions = byClass(row, "inbox-action");
  assert.deepEqual(actions.map((node) => node.textContent), ["Deny", "Approve"]);

  actions[1].dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(
    client.requests.filter(
      (request) => request.function === "decision_requests.resolve",
    ),
    [{
      function: "decision_requests.resolve",
      payload: { request_id: 42, action: "approve" },
    }],
  );
  // Answered, so the panel has nothing left to ask and steps aside.
  assert.equal(byClass(main, "inbox-row").length, 0);
  assert.equal(main.children[0].children[0].hidden, true);
});

test("a machine with no code or requester says so rather than inventing one", async () => {
  const { main } = renderMachines([approvalRow({
    subject_context: {},
    originator_actor_label: null,
  })]);
  await settle();

  const subtitle = byClass(main, "inbox-row-subtitle")[0].textContent;
  assert.ok(subtitle.includes("machine not named"), subtitle);
  assert.ok(subtitle.includes("no one-time code delivered"), subtitle);
  assert.ok(!subtitle.includes("requested by"), subtitle);
});

test("nothing waiting leaves the machines page unasked", async () => {
  const { main } = renderMachines([]);
  await settle();

  assert.equal(byClass(main, "inbox-row").length, 0);
  assert.equal(main.children[0].children[0].hidden, true);
});
