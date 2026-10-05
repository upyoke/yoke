import assert from "node:assert/strict";
import test from "node:test";
import { renderNewItemView } from "../../packages/yoke-core/src/yoke_core/ui/static/item_view_new.js";
import { itemDraftStorage } from "../../packages/yoke-core/src/yoke_core/ui/static/item_draft_storage.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { itemContext } from "./universe_ui_items_test_support.mjs";

const ok = (result) => ({ status: 200, envelope: { success: true, result } });
const failure = { status: 503, envelope: { success: false, error: { message: "Unavailable" } } };
function fixture({ projects = [{ id: 7, slug: "acme", name: "Acme" }] } = {}) {
  const document = new FakeDocument();
  const entries = new Map();
  document.defaultView.sessionStorage = {
    getItem: (key) => entries.get(key),
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  };
  Object.assign(document.defaultView.location, { origin: "https://example.test", pathname: "/acme/work" });
  const state = { actor: 7, unavailable: false, workflows: ["dash"], mounted: true, navigated: [] };
  const context = itemContext(document, async (request) => {
    if (request.function === "organizations.get") return ok({ slug: "acme" });
    if (request.function === "profile.get") return ok({ actor: { id: state.actor } });
    if (request.function === "workflows.definition.get") return state.unavailable ? failure : ok({
      title_max_length: 100,
      workflows: state.workflows.map((id) => ({ id, name: id, definition: { entry_surfaces: ["web_form"], policies: { item_posture_allowlist: [] } } })),
    });
    if (request.function === "items.create") return state.create?.(request) || ok({ public_ref: ["ACM", 23].join("-") });
    return ok({ rows: [] });
  });
  const call = context.client.call;
  context.client.call = (request) => request.function === "projects.list" && request.payload.for_item_creation
    ? Promise.resolve(ok({ creation_scoped: true, rows: projects })) : call(request);
  context.projects = () => projects;
  context.isMounted = () => state.mounted;
  context.navigate = (href) => state.navigated.push(href);
  const main = document.createElement("main");
  const mount = async (initialProjectId = "7") => { renderNewItemView(context, main, initialProjectId); await settle(); await settle(); };
  return { context, document, main, entries, state, mount };
}
const input = (main, tag) => allNodes(main).find((node) => node.tagName === tag);
function fill(main) {
  for (const [tag, value] of [["INPUT", "Fix layout"], ["TEXTAREA", "Preserve the useful draft."]]) {
    const control = input(main, tag);
    control.value = value;
    control.dispatchEvent(new Event("input"));
    control.dispatchEvent(new Event("blur"));
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

test("All-project creation restores its chosen project and draft after remount", async () => {
  const { mount, main } = fixture({ projects: [
    { id: 7, slug: "harbour", name: "Harbour" },
    { id: 8, slug: "garden", name: "Garden" },
  ] });
  await mount("all");
  assert.equal(input(main, "TEXTAREA"), undefined);
  const selector = byClass(main, "item-project-select")[0];
  selector.value = "7";
  selector.dispatchEvent(new Event("change"));
  await settle();
  fill(main);
  await mount("all");
  assert.equal(byClass(main, "item-project-select")[0].value, "7");
  assert.equal(input(main, "INPUT").value, "Fix layout");
  assert.equal(input(main, "TEXTAREA").value, "Preserve the useful draft.");
});

test("an explicit workflow link takes precedence over the saved draft workflow", async () => {
  const { mount, main, state, document } = fixture();
  await mount(); fill(main);
  state.workflows = ["dash", "task"];
  document.defaultView.location.href = "/items/new?workflow=task";
  await mount();
  assert.equal(input(main, "INPUT").value, "Fix layout");
  assert.ok(allNodes(main).some((node) => node.tagName === "BUTTON" && node.textContent === "Create task"));
});

function deferCreation(state) {
  let resolve;
  const pending = new Promise((done) => { resolve = done; });
  state.create = () => pending;
  return () => resolve(ok({ public_ref: ["ACM", 24].join("-") }));
}

for (const editNewForm of [false, true]) {
  test(`a detached create response preserves a remounted draft${editNewForm ? " with newer text" : " with identical text"}`, async () => {
    const { mount, main, state, entries } = fixture();
    await mount(); fill(main);
    const complete = deferCreation(state);
    input(main, "FORM").dispatchEvent(new Event("submit"));
    await settle();
    await mount();
    if (editNewForm) {
      const title = input(main, "INPUT");
      title.value = "A newer draft";
      title.dispatchEvent(new Event("input"));
    }
    const saved = [...entries.values()][0];
    complete(); await settle();
    assert.equal([...entries.values()][0], saved);
    assert.equal(state.navigated.length, 0);
    assert.equal(input(main, "INPUT").value, editNewForm ? "A newer draft" : "Fix layout");
  });
}

test("edits made during creation survive and remain usable in the same form", async () => {
  const { mount, main, state, entries } = fixture();
  await mount(); fill(main);
  const complete = deferCreation(state);
  const form = input(main, "FORM");
  form.dispatchEvent(new Event("submit"));
  const instruction = input(main, "TEXTAREA");
  instruction.value = "A different instruction written while waiting.";
  instruction.dispatchEvent(new Event("input"));
  const saved = [...entries.values()][0];
  complete(); await settle();
  assert.notEqual([...entries.values()][0], saved);
  assert.equal(JSON.parse([...entries.values()][0]).instruction, instruction.value);
  assert.equal(state.navigated.length, 0);
  assert.equal(input(main, "FORM"), form);
  assert.match(main.textContent, /Created.*Your newer draft is kept/);
  assert.equal(allNodes(main).find((node) => node.type === "submit").disabled, false);
});

test("an unmounted create completion clears only its submitted draft without navigation", async () => {
  const { mount, main, state, entries } = fixture();
  await mount(); fill(main);
  const complete = deferCreation(state);
  input(main, "FORM").dispatchEvent(new Event("submit"));
  state.mounted = false;
  complete(); await settle();
  assert.equal(entries.size, 0);
  assert.equal(state.navigated.length, 0);
});

test("typing saves once after the pause, while blur flushes immediately", async () => {
  const { mount, main, entries } = fixture();
  await mount();
  const before = [...entries.values()][0];
  const title = input(main, "INPUT");
  title.value = "One";
  title.dispatchEvent(new Event("input"));
  await new Promise((resolve) => setTimeout(resolve, 550));
  title.value = "Two";
  title.dispatchEvent(new Event("input"));
  await new Promise((resolve) => setTimeout(resolve, 550));
  assert.equal([...entries.values()][0], before);
  await new Promise((resolve) => setTimeout(resolve, 550));
  assert.equal(JSON.parse([...entries.values()][0]).title, "Two");
  title.value = "Blurred";
  title.dispatchEvent(new Event("input"));
  title.dispatchEvent(new Event("blur"));
  const flushed = [...entries.values()][0];
  assert.equal(JSON.parse(flushed).title, "Blurred");
  await new Promise((resolve) => setTimeout(resolve, 1100));
  assert.equal([...entries.values()][0], flushed);
});

for (const event of ["pagehide", "visibilitychange"]) {
  test(`${event} flushes a pending draft save`, async () => {
    const { mount, main, entries, document } = fixture();
    await mount();
    const title = input(main, "INPUT");
    title.value = "Leaving";
    title.dispatchEvent(new Event("input"));
    document.visibilityState = "hidden";
    (event === "pagehide" ? document.defaultView : document).dispatchEvent(new Event(event));
    assert.equal(JSON.parse([...entries.values()][0]).title, "Leaving");
  });
}
