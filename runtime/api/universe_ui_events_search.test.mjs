import assert from "node:assert/strict";
import test from "node:test";
import { renderEventsView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_events.js";
import { FakeDocument, allNodes, byClass, settle } from "./universe_ui_dom_test_support.mjs";

const ok = (rows) => ({ status: 200, envelope: { success: true, result: { rows } } });
function mount(call) {
  const document = new FakeDocument();
  const main = document.createElement("main");
  renderEventsView({ document, client: { call }, isMounted: () => true, projects: () => [{ id: 1 }] }, main, [1]);
  return main;
}
const button = (main, label) => allNodes(main).find((node) => node.tagName === "BUTTON" && node.textContent === label);
const names = (main) => byClass(main, "event-name").map((node) => node.textContent);

test("friendly event search matches loaded context without fetching, and clears", async () => {
  let calls = 0;
  const main = mount(async () => {
    calls += 1;
    return ok([
      { event_name: "deployment.completed", context_label: "Shipped the footer", target_label: "Design", source_type: "flow", created_at: "2026-01-01T00:00:00Z" },
      { event_name: "session.started", context_label: "Started work", target_label: "Tools", source_type: "session", created_at: "2026-01-01T00:00:00Z" },
    ]);
  });
  await settle();
  const search = byClass(main, "event-criterion").find((node) => node.textContent.includes("Search loaded entries")).children[1];
  search.value = "footer";
  search.dispatchEvent(new Event("input"));
  assert.deepEqual(names(main), ["deployment.completed"]);
  assert.equal(calls, 1);
  assert.match(main.textContent, /1 of 2 loaded entries shown/);
  search.value = "tools";
  search.dispatchEvent(new Event("input"));
  assert.deepEqual(names(main), ["session.started"]);
  button(main, "Clear search").dispatchEvent(new Event("click"));
  assert.equal(names(main).length, 2);
  const suggestions = allNodes(main).filter((node) => node.tagName === "DATALIST");
  assert.deepEqual(suggestions[0].children.map((node) => node.value), ["deployment.completed", "session.started"]);
  assert.deepEqual(suggestions[1].children.map((node) => node.value), ["flow", "session"]);
});

test("first-page event failure has a working retry with the controls preserved", async () => {
  let calls = 0;
  const main = mount(async () => ++calls === 1
    ? { status: 503, envelope: { success: false, error: { message: "Unavailable" } } }
    : ok([{ event_name: "Recovered", created_at: "2026-01-01T00:00:00Z" }]));
  await settle();
  const controls = byClass(main, "event-controls")[0];
  button(main, "Try again").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(byClass(main, "event-controls")[0], controls);
  assert.deepEqual(names(main), ["Recovered"]);
  assert.equal(calls, 2);
});
