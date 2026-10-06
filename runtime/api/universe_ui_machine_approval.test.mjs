import assert from "node:assert/strict";
import test from "node:test";
import { renderMachineApproval } from "../../packages/yoke-core/src/yoke_core/ui/static/machine_approval.js";
import { parseUniverseRoute } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_navigation.js";
import { FakeDocument, allNodes, settle } from "./universe_ui_dom_test_support.mjs";

function page({ decision = null, failure = false } = {}) {
  const document = new FakeDocument();
  const main = document.createElement("div");
  const requests = [];
  let refuse = failure;
  const context = {
    document, isMounted: () => true,
    client: {
      async call(request) {
        requests.push(request);
        if (request.function === "machine_authorization.resolve" && refuse) {
          refuse = false;
          return { status: 409, envelope: { success: false, error: { message: "authorization_expired: start a fresh code" } } };
        }
        return { status: 200, envelope: { success: true, result: {
          authorization: request.function === "machine_authorization.get"
            ? { code: "ABCDE-12345", machine: "My laptop", machine_id: "machine-id", expires_at: "2030-01-01", decision }
            : { decision: request.payload.action },
        } } };
      },
    },
  };
  renderMachineApproval(context, main, null, "ABCDE-12345");
  return { main, requests, context };
}

const button = (main, label) => allNodes(main).find((node) => node.tagName === "BUTTON" && node.textContent === label);

test("approval route retains the code and displays the machine before the personal decision", async () => {
  assert.equal(parseUniverseRoute("/machine-approval/ABCDE-12345").detail, "ABCDE-12345");
  const { main, requests } = page();
  await settle();
  assert.match(main.textContent, /My laptop/);
  assert.match(main.textContent, /your own machine/);
  button(main, "Approve my machine").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(requests[1].payload, { code: "ABCDE-12345", action: "approve" });
  assert.match(main.textContent, /Return to your CLI/);
  assert.equal(button(main, "Deny"), undefined);
});

test("denial directs the person to start another code", async () => {
  const { main } = page();
  await settle();
  button(main, "Deny").dispatchEvent(new Event("click"));
  await settle();
  assert.match(main.textContent, /Machine denied.*fresh connection/);
});

test("a failed decision remains visible and retryable", async () => {
  const { main, requests } = page({ failure: true });
  await settle();
  const approve = button(main, "Approve my machine");
  approve.dispatchEvent(new Event("click"));
  await settle();
  assert.match(main.textContent, /authorization_expired/);
  assert.equal(approve.disabled, false);
  approve.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(requests.length, 3);
  assert.match(main.textContent, /Machine approved/);
});

test("a decided code does not offer a second approval", async () => {
  const { main } = page({ decision: "approve" });
  await settle();
  assert.equal(button(main, "Approve my machine"), undefined);
  assert.match(main.textContent, /Return to your CLI/);
});
