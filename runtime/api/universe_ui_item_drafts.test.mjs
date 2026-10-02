import assert from "node:assert/strict";
import test from "node:test";
import { renderNewItemView } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_new.js";
import { itemDraftStorage } from "../../packages/yoke-core/src/yoke_core/ui/static/item_draft_storage.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { itemContext } from "./universe_ui_items_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const failure = { status: 503, envelope: { success: false, error: { message: "Unavailable" } } };
function fixture() {
  const document = new FakeDocument();
  const entries = new Map();
  document.defaultView.sessionStorage = {
    getItem: (key) => entries.get(key),
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  };
  Object.assign(document.defaultView.location, { origin: "https://example.test", pathname: "/acme/work" });
  const state = { actor: 7, unavailable: false };
  const context = itemContext(document, async (request) => {
    if (request.function === "organizations.get") return ok({ slug: "acme" });
    if (request.function === "profile.get") return ok({ actor: { id: state.actor } });
    if (request.function === "workflows.definition.get") return state.unavailable ? failure : ok({
      title_max_length: 100,
      workflows: [{ id: "dash", name: "Dash", definition: { entry_surfaces: ["web_form"], policies: { item_posture_allowlist: [] } } }],
    });
    if (request.function === "items.create") return ok({ public_ref: "ACM-23" });
    return ok({ rows: [] });
  });
  const main = document.createElement("main");
  const mount = async () => { renderNewItemView(context, main, "7"); await settle(); await settle(); };
  return { context, document, main, entries, state, mount };
}
const input = (main, tag) => allNodes(main).find((node) => node.tagName === tag);
function fill(main) {
  for (const [tag, value] of [["INPUT", "Fix layout"], ["TEXTAREA", "Preserve the useful draft."]]) {
    const control = input(main, tag);
    control.value = value;
    control.dispatchEvent(new Event("input"));
  }
}

test("new item survives remount, stays isolated by actor/universe, and discards explicitly", async () => {
  const { mount, main, state, document } = fixture();
  await mount(); fill(main); await mount();
  assert.equal(input(main, "INPUT").value, "Fix layout");
  assert.equal(input(main, "TEXTAREA").value, "Preserve the useful draft.");
  state.actor = 8; await mount();
  assert.equal(input(main, "INPUT").value, "");
  state.actor = 7; document.defaultView.location.pathname = "/other/work"; await mount();
  assert.equal(input(main, "INPUT").value, "");
  document.defaultView.location.pathname = "/acme/work"; await mount();
  allNodes(main).find((node) => node.tagName === "A" && node.textContent === "Discard draft").dispatchEvent(new Event("click"));
  await mount();
  assert.equal(input(main, "INPUT").value, "");
});

test("successful creation clears the draft", async () => {
  const { mount, main, entries } = fixture();
  await mount(); fill(main);
  input(main, "FORM").dispatchEvent(new Event("submit"));
  await settle();
  assert.equal(entries.size, 0);
});

test("failed project refresh offers retry with the draft intact", async () => {
  const { mount, main, state } = fixture();
  await mount(); fill(main);
  state.unavailable = true;
  byClass(main, "item-project-select")[0].dispatchEvent(new Event("change"));
  await settle();
  assert.match(main.textContent, /Unavailable/);
  state.unavailable = false;
  allNodes(main).find((node) => node.textContent === "Try again").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(input(main, "INPUT").value, "Fix layout");
});

test("draft restore checks current project permission and tolerates unavailable storage", async () => {
  const { context, mount, main, document } = fixture();
  await mount(); fill(main);
  const store = await itemDraftStorage(context);
  assert.equal(store.read([], "7"), null);
  assert.equal(store.read([{ id: 7 }], "8"), null);
  Object.defineProperty(document.defaultView, "sessionStorage", { get() { throw new Error("Blocked"); } });
  assert.equal(await itemDraftStorage(context), null);
  await mount();
  assert.ok(input(main, "TEXTAREA"));
});
