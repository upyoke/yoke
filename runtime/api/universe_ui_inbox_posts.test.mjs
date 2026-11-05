import assert from "node:assert/strict";
import test from "node:test";
import { FakeDocument, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { inboxSection, ok } from "./universe_ui_inbox_test_support.mjs";
import { renderInboxView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js";

function render({ failDone = false, oldServer = false } = {}) {
  const document = new FakeDocument();
  const main = document.createElement("main");
  const requests = [];
  let posts = [{ id: 4, project_id: 10, title: "<script>alert(1)</script>", body: "Read <b>this</b>", source: "External form", fields: { Email: "<img src=x>" } }];
  const client = { async call(request) {
    requests.push(request);
    if (request.function === "inbox.list") return ok({ needs_decision: [], messages: [], ...(oldServer ? {} : { posts }) });
    if (request.function === "inbox.posts.done") {
      if (failDone) return { status: 403, envelope: { success: false, error: { code: "not_in_audience", message: "Ask a current audience member." } } };
      posts = [];
      return ok({ post: { done_by: "Morgan", done_at: "2026-11-05T12:00:00Z", already_done: true } });
    }
    throw new Error(request.function);
  } };
  renderInboxView({ document, client, isMounted: () => true, projects: () => [{ id: 10, name: "Example" }] }, main, "all");
  return { main, requests };
}

test("posts use text nodes, carry source and Done clears the shared card", async () => {
  const { main, requests } = render();
  await settle();
  const card = byClass(main, "inbox-post-card")[0];
  assert.match(card.textContent, /<script>alert\(1\)<\/script>/);
  assert.match(card.textContent, /<img src=x>/);
  assert.equal(card.children.some((node) => node.tagName === "SCRIPT" || node.tagName === "IMG"), false);
  const button = byClass(card, "item-button")[0];
  button.dispatchEvent(new Event("click"));
  assert.equal(button.disabled, true);
  await settle();
  assert.deepEqual(requests.find((request) => request.function === "inbox.posts.done").payload, { post_id: 4 });
  assert.equal(byClass(main, "inbox-post-card").length, 0);
  assert.match(byClass(main, "inbox-post-completion")[0].textContent, /Done by Morgan/);
});

test("a refusal keeps the post visible and restores Done with recovery", async () => {
  const { main } = render({ failDone: true });
  await settle();
  const button = byClass(main, "item-button")[0];
  button.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(button.disabled, false);
  assert.equal(byClass(main, "inbox-post-card").length, 1);
  assert.match(byClass(main, "inbox-row-error")[0].textContent, /Ask a current audience member/);
});

test("older serving responses keep the existing Inbox usable", async () => {
  const { main } = render({ oldServer: true });
  await settle();
  assert.equal(inboxSection(main, "posts").hidden, true);
  assert.equal(byClass(main, "inbox-row-error").length, 0);
});
