import assert from "node:assert/strict";
import test from "node:test";
import { byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { inboxSection, renderInbox } from "./universe_ui_inbox_test_support.mjs";

function question(overrides = {}) {
  return {
    id: 9, kind: "operator_question", status: "pending", project_id: 10,
    requesting_session_id: "worker", requesting_session_label: "Morgan · Codex",
    subject_context: { question: "Which color?", options: [
      { id: "blue", label: "Blue", detail: "Matches the header" },
      { id: "green", label: "Green" },
    ], recommended_option: "blue", allow_freeform: true },
    actions: ["blue", "green", "freeform"], ...overrides,
  };
}

test("a recommended option resolves the same request and moves its card to Decided", async () => {
  const { main, client } = renderInbox("all", [question()]);
  await settle();
  const options = byClass(main, "inbox-question-option");
  assert.equal(options[0].textContent, "Blue");
  assert(options[0].classList.contains("primary"));
  assert.match(byClass(main, "inbox-question-choice")[0].textContent, /Recommended/);
  options[0].dispatchEvent(new Event("click"));
  await settle();
  const call = client.requests.find((request) => request.function === "decision_requests.resolve");
  assert.deepEqual(call.payload, { request_id: 9, action: "blue" });
  assert.equal(byClass(inboxSection(main, "waiting"), "inbox-question-card").length, 0);
  assert.match(inboxSection(main, "decided").textContent, /Which color\?.*Blue/);
});

test("freeform Send requires text and retains the answer after resolution", async () => {
  const { main, client } = renderInbox("all", [question()]);
  await settle();
  const input = byClass(main, "item-form-control")[0];
  const send = byClass(main, "inbox-question-send")[0];
  assert.equal(send.disabled, true);
  input.value = "Use violet";
  input.dispatchEvent(new Event("input"));
  assert.equal(send.disabled, false);
  send.dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(client.requests.find((request) => request.function === "decision_requests.resolve").payload,
    { request_id: 9, action: "freeform", note: "Use violet" });
  assert.match(inboxSection(main, "decided").textContent, /Use violet/);
});

test("settled questions show the saved answer without controls after reload", async () => {
  const { main } = renderInbox("all", [question({ status: "resolved", decided_by_you: true,
    actions: [], resolution_action: "freeform", resolution_note: "Use violet\nLater detail" })]);
  await settle();
  assert.match(inboxSection(main, "decided").textContent, /Use violet/);
  assert.equal(byClass(main, "inbox-question-send").length, 0);
  assert.doesNotMatch(inboxSection(main, "decided").textContent, /Later detail/);
});

test("choice-only questions do not offer freeform input", async () => {
  const { main } = renderInbox("all", [question({ actions: ["blue", "green"] })]);
  await settle();
  assert.equal(byClass(main, "inbox-question-freeform").length, 0);
});


test("keyboard send keeps typed text and reports a named error inline on failure", async () => {
  const { main, client } = renderInbox("all", [question()]);
  const call = client.call.bind(client);
  client.call = (request) => request.function === "decision_requests.resolve"
    ? Promise.resolve({ status: 503, envelope: { success: false,
      error: { code: "storage_unavailable", message: "Retry Send." } } }) : call(request);
  await settle();
  const input = byClass(main, "item-form-control")[0];
  input.value = "Keep this answer";
  input.dispatchEvent(new Event("input"));
  input.dispatchEvent(Object.assign(new Event("keydown"), { key: "Enter", ctrlKey: true }));
  await settle();
  assert.equal(input.value, "Keep this answer");
  assert.match(byClass(main, "inbox-row-error")[0].textContent, /storage_unavailable.*Retry Send/);
  assert.equal(byClass(inboxSection(main, "waiting"), "inbox-question-card").length, 1);
});
