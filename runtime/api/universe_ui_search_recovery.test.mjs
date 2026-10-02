import assert from "node:assert/strict";
import test from "node:test";

import { createUniverseSearch } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_search_domains.js";
import { byClass, settle, visibleText } from "./universe_ui_dom_test_support.mjs";
import { fixtureClient, mountShell, ok, refused, settleSearch } from "./universe_ui_search_test_support.mjs";

const control = (root, name) => byClass(root, name)[0];
const click = (node) => node.dispatchEvent(new Event("click"));
const press = (node, key) => {
  const event = new Event("keydown");
  event.key = key;
  node.dispatchEvent(event);
};
async function query(root, text) {
  const input = control(root, "header-search-input");
  input.value = text;
  input.dispatchEvent(new Event("input"));
  await settleSearch();
  return input;
}

test("reopening search loads fresh catalogues while queries within one open reuse them", async (t) => {
  let name = "rebaseline first";
  const calls = [];
  const { root } = await mountShell(t, fixtureClient({ calls, overrides: {
    "strategy.doc.list": (_payload, target) => ok({ docs: target.project_id === "1"
      ? [{ slug: name, title: name }] : [] }),
  } }));
  const open = () => click(control(root, "header-search"));
  open();
  await query(root, "rebaseline");
  assert.match(visibleText(control(root, "header-search-body")), /rebaseline first/);
  name = "rebaseline second";
  await query(root, "rebaseline second");
  assert.equal(calls.filter((call) => call.function === "strategy.doc.list").length, 2);
  click(control(root, "header-search-close"));
  open();
  await query(root, "rebaseline");
  const text = visibleText(control(root, "header-search-body"));
  assert.match(text, /rebaseline second/);
  assert.doesNotMatch(text, /rebaseline first/);
  assert.equal(calls.filter((call) => call.function === "strategy.doc.list").length, 4);
});

test("a failed domain offers an explicit retry without reloading the page", async (t) => {
  let unavailable = true;
  const { documentNode, root } = await mountShell(t, fixtureClient({ overrides: {
    "packs.list": () => unavailable ? refused()
      : ok({ packs: [{ slug: "rebaseline-recovered", name: "Rebaseline recovered" }] }),
  } }));
  click(control(root, "header-search"));
  const input = await query(root, "rebaseline");
  assert.match(visibleText(control(root, "header-search-body")), /Could not search Packs/);
  unavailable = false;
  click(byClass(root, "header-search-row").find((node) => node.textContent === "Retry search"));
  await settle();
  const text = visibleText(control(root, "header-search-body"));
  assert.match(text, /Rebaseline recovered/);
  assert.doesNotMatch(text, /Could not search/);
  assert.equal(documentNode.activeElement, input);
});

test("a late domain preserves the selected result, its identity and keyboard focus", async (t) => {
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const { documentNode, root } = await mountShell(t, fixtureClient({ overrides: {
    "items.search.run": async () => {
      await held;
      return ok({ matches: [{ id: ["DEMO", 1].join("-"), title: "Rebaseline newest", project_id: 1 }] });
    },
  } }));
  click(control(root, "header-search"));
  const input = await query(root, "rebaseline");
  press(input, "ArrowDown");
  const selected = control(root, "header-search-result");
  const selectedId = selected.id;
  selected.focus();
  release();
  await settle();
  const results = byClass(root, "header-search-result");
  assert.equal(results[1], selected);
  assert.equal(input.getAttribute("aria-activedescendant"), selectedId);
  assert.equal(selected.getAttribute("aria-selected"), "true");
  assert.equal(documentNode.activeElement, selected);
  input.focus();
  press(input, "Enter");
  assert.equal(documentNode.defaultView.location.hash, selected.href);
});

test("ArrowUp starts at the last result and clearing the query clears selection", async (t) => {
  const { root } = await mountShell(t, fixtureClient());
  click(control(root, "header-search"));
  const input = await query(root, "rebaseline");
  press(input, "ArrowUp");
  const last = byClass(root, "header-search-result").at(-1);
  assert.equal(input.getAttribute("aria-activedescendant"), last.id);
  assert.equal(last.getAttribute("aria-selected"), "true");
  await query(root, "r");
  assert.equal(input.getAttribute("aria-activedescendant"), null);
  await query(root, "");
  assert.equal(input.getAttribute("aria-activedescendant"), null);
});

test("failed project catalogue reads stay unavailable and retry on the next query", async () => {
  let unavailable = true;
  const client = fixtureClient({ overrides: {
    "projects.list": () => unavailable ? refused()
      : ok({ rows: [{ id: 3, slug: "demo" }] }),
  } });
  const search = createUniverseSearch(client);
  const answers = new Map();
  await search("rebaseline", (domain, entries) => answers.set(domain.key, entries));
  assert.equal(answers.get("strategy"), null);
  unavailable = false;
  await search("rebaseline", (domain, entries) => answers.set(domain.key, entries));
  assert.equal(answers.get("strategy")[0].label, "Rebaseline plan");
});

test("an empty project catalogue is empty rather than unavailable", async () => {
  const search = createUniverseSearch(fixtureClient({ overrides: {
    "projects.list": () => ok({ rows: [] }),
  } }));
  const answers = new Map();
  await search("rebaseline", (domain, entries) => answers.set(domain.key, entries));
  for (const key of ["strategy", "qa-plans", "packs"]) assert.deepEqual(answers.get(key), []);
});
