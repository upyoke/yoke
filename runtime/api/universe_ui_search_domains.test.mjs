// What universe search covers: six domains, every project, and an honest
// answer when a read refuses or a catalogue is slow.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, settle } from "./universe_ui_dom_test_support.mjs";
import {
  fixtureClient, mountShell, ok, refused, settleSearch,
} from "./universe_ui_search_test_support.mjs";

test("a query reaches all six domains across every project", async (t) => {
  const calls = [];
  const { root } = await mountShell(t, fixtureClient({ calls }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "rebaseline";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  const groups = byClass(root, "header-search-section-label")
    .map((node) => node.textContent);
  assert.deepEqual(groups, [
    "Items", "Sessions", "Strategy docs", "QA plans", "Events", "Packs",
  ]);
  const results = byClass(root, "header-search-result");
  assert.deepEqual(results.map((node) => node.href), [
    "#/items/2228?project=1",
    "#/sessions/session-rebaseline?project=1",
    // The strategy doc lives in the OTHER project and is found anyway.
    "#/strategy/REBASELINE-PLAN?project=3",
    "#/qa-plans/298?project=1",
    "#/events?project=1",
    "#/packs",
  ]);
  // Each result says which project it is in, because scope never narrowed.
  assert.match(byClass(root, "header-search-meta")[2].textContent, /platform/);

  // A project-scoped read is asked of every project, never of the selection.
  const packProjects = calls
    .filter((call) => call.function === "packs.list")
    .map((call) => call.payload.project);
  assert.deepEqual(packProjects.sort(), ["1", "3"]);
  const docProjects = calls
    .filter((call) => call.function === "strategy.doc.list")
    .map((call) => call.target.project_id);
  assert.deepEqual(docProjects.sort(), ["1", "3"]);

  // Searching something that matched is what gets remembered.
  const recorded = calls.find(
    (call) => call.function === "ui_preferences.search_history.record",
  );
  assert.deepEqual(recorded.payload, { query: "rebaseline" });
});

test("a domain that refused is named rather than read as empty", async (t) => {
  const { root } = await mountShell(t, fixtureClient({
    overrides: { "packs.list": () => refused() },
  }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "rebaseline";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  assert.equal(byClass(root, "header-search-section-label").length, 5);
  const hints = byClass(root, "header-search-hint").map((n) => n.textContent);
  assert.match(hints.at(-1), /Could not search Packs/);
  assert.match(hints.at(-1), /missing, not absent/);
});

test("a query that matches nothing says so without blaming the index", async (t) => {
  const empty = () => ok({ matches: [], rows: [], docs: [], packs: [] });
  const { root } = await mountShell(t, fixtureClient({
    overrides: {
      "items.search.run": empty,
      "sessions.list": empty,
      "strategy.doc.list": empty,
      "qa.plan.list": empty,
      "events.query.run": empty,
      "packs.list": empty,
    },
  }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "nothing-here";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  assert.match(
    byClass(root, "header-search-status")[0].textContent,
    /Nothing matches “nothing-here”/,
  );
  assert.equal(byClass(root, "header-search-result").length, 0);
});

test("a slow domain does not hold the fast ones hostage", async (t) => {
  let releaseSlowRead = null;
  const held = new Promise((resolve) => { releaseSlowRead = resolve; });
  const { root } = await mountShell(t, fixtureClient({
    overrides: {
      "packs.list": async (payload) => {
        await held;
        return ok({ packs: String(payload?.project) === "1"
          ? [{ slug: "rebaseline-pack", name: "Rebaseline Pack" }] : [] });
      },
    },
  }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "rebaseline";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  // Five domains have answered and are on screen; the sixth is still going,
  // and the panel says so rather than pretending it found nothing.
  assert.equal(byClass(root, "header-search-section-label").length, 5);
  assert.equal(byClass(root, "header-search-result").length, 5);
  assert.match(
    byClass(root, "header-search-status")[0].textContent, /Searching/,
  );

  releaseSlowRead();
  await settle();
  assert.equal(byClass(root, "header-search-section-label").length, 6);
  assert.equal(byClass(root, "header-search-status").length, 0);
});

test("a second query re-reads the keyword search, not every catalogue", async (t) => {
  const calls = [];
  const { root } = await mountShell(t, fixtureClient({ calls }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  const countOf = (fn) => calls.filter((call) => call.function === fn).length;

  input.value = "rebaseline";
  input.dispatchEvent(new Event("input"));
  await settleSearch();
  // Two projects, so the first query pays one read per project per catalogue.
  assert.equal(countOf("packs.list"), 2);
  assert.equal(countOf("items.search.run"), 1);

  input.value = "workbench";
  input.dispatchEvent(new Event("input"));
  await settleSearch();
  // A catalogue does not change while somebody is typing, so the second
  // query costs the keyword reads alone rather than another fan-out.
  assert.equal(countOf("packs.list"), 2);
  assert.equal(countOf("qa.plan.list"), 2);
  assert.equal(countOf("strategy.doc.list"), 2);
  assert.equal(countOf("items.search.run"), 2);
});

test("a query that found nothing is not offered back as Recent", async (t) => {
  const calls = [];
  const empty = () => ok({ matches: [], rows: [], docs: [], packs: [] });
  const { root } = await mountShell(t, fixtureClient({
    calls,
    overrides: {
      "items.search.run": empty,
      "sessions.list": empty,
      "strategy.doc.list": empty,
      "qa.plan.list": empty,
      "events.query.run": empty,
      "packs.list": empty,
    },
  }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "nothing-here";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  assert.equal(
    calls.filter(
      (call) => call.function === "ui_preferences.search_history.record",
    ).length,
    0,
  );
});
