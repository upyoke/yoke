// The search dialog itself: how it opens, what it opens on, and how a
// keyboard drives it. What it searches is its sibling suite.

import assert from "node:assert/strict";
import test from "node:test";

import { byClass, settle, visibleText } from "./universe_ui_dom_test_support.mjs";
import {
  fixtureClient, mountShell, ok, settleSearch,
} from "./universe_ui_search_test_support.mjs";

test("the dialog opens on what search covers, not on invented results", async (t) => {
  const calls = [];
  const client = fixtureClient({
    calls,
    overrides: {
      "ui_preferences.search_history.list": () => ok({
        queries: ["YOK-2228", "release-readiness"],
      }),
    },
  });
  const { documentNode, root } = await mountShell(t, client);

  const overlay = byClass(root, "header-search-overlay")[0];
  assert.equal(overlay.hidden, true);
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.equal(overlay.hidden, false);
  assert.equal(
    documentNode.activeElement, byClass(root, "header-search-input")[0],
  );

  // Every domain the dialog advertises, in the order results arrive in.
  assert.deepEqual(
    byClass(root, "header-search-chip").map((node) => node.textContent),
    ["Items", "Sessions", "Strategy docs", "QA plans", "Events", "Packs"],
  );
  // The scope rule is stated where the operator is deciding what to type.
  const hint = byClass(root, "header-search-hint")[0].textContent;
  assert.match(hint, /project selector does not narrow it/);
  assert.match(hint, /which project it is in/);

  // Recent is this actor's own stored history, read from the control plane.
  assert.deepEqual(
    byClass(root, "header-search-row").map((node) => node.textContent),
    ["YOK-2228", "release-readiness"],
  );
  assert.ok(calls.some(
    (call) => call.function === "ui_preferences.search_history.list",
  ));
  // Nothing was searched, so nothing claims to have matched.
  assert.equal(byClass(root, "header-search-result").length, 0);
});

test("one character is not a query", async (t) => {
  const calls = [];
  const { root } = await mountShell(t, fixtureClient({ calls }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "r";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  assert.match(
    byClass(root, "header-search-status")[0].textContent,
    /at least 2 characters/,
  );
  assert.equal(
    calls.filter((call) => call.function === "items.search.run").length, 0,
  );
});

test("the shortcut opens and closes the same dialog from anywhere", async (t) => {
  const { documentNode, root } = await mountShell(t, fixtureClient());
  const overlay = byClass(root, "header-search-overlay")[0];
  const shortcut = () => {
    const event = new Event("keydown");
    Object.defineProperties(event, {
      key: { value: "k" }, metaKey: { value: true }, ctrlKey: { value: false },
    });
    documentNode.defaultView.dispatchEvent(event);
  };
  shortcut();
  await settle();
  assert.equal(overlay.hidden, false);
  shortcut();
  assert.equal(overlay.hidden, true);

  // Escape is the way out wherever focus sits: a modal owns the whole page
  // while it is open, so its dismissal is window-level too.
  shortcut();
  await settle();
  const escape = new Event("keydown");
  Object.defineProperty(escape, "key", { value: "Escape" });
  documentNode.defaultView.dispatchEvent(escape);
  assert.equal(overlay.hidden, true);
});

test("arrow keys walk the results and Enter follows the active one", async (t) => {
  const { documentNode, root } = await mountShell(t, fixtureClient());
  byClass(root, "header-search-button")[0].dispatchEvent(new Event("click"));
  const input = byClass(root, "header-search-input")[0];
  input.value = "rebaseline";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  const key = (name) => {
    const event = new Event("keydown");
    Object.defineProperty(event, "key", { value: name });
    input.dispatchEvent(event);
  };
  key("ArrowDown");
  key("ArrowDown");
  const results = byClass(root, "header-search-result");
  assert.equal(results[1].classList.contains("active"), true);
  assert.equal(
    input.getAttribute("aria-activedescendant"), results[1].id,
  );
  key("Enter");
  assert.equal(
    documentNode.defaultView.location.hash,
    "#/sessions/session-rebaseline?project=1",
  );
  assert.equal(byClass(root, "header-search-overlay")[0].hidden, true);
});

test("a recent query re-runs it rather than only filling the field", async (t) => {
  const { root } = await mountShell(t, fixtureClient({
    overrides: {
      "ui_preferences.search_history.list": () => ok({
        queries: ["rebaseline"],
      }),
    },
  }));
  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  await settle();
  byClass(root, "header-search-row")[0].dispatchEvent(new Event("click"));
  await settle();

  assert.equal(byClass(root, "header-search-input")[0].value, "rebaseline");
  assert.ok(visibleText(byClass(root, "header-search-body")[0])
    .includes("Rebaseline the workbench"));
});

// A modal that outlives the screen it was opened over stops being a dialog
// and becomes an invisible click-blocker: its backdrop goes on swallowing
// pointer events over a page the operator never opened it from, and nothing
// on screen explains why. Found on the deployed product, where every click
// after a route change reported the backdrop intercepting it while the page
// looked perfectly rendered.
test("a route change closes the dialog rather than leaving its backdrop over the next screen", async (t) => {
  const client = fixtureClient({});
  const { documentNode, root } = await mountShell(t, client);
  const overlay = byClass(root, "header-search-overlay")[0];

  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  await settle();
  assert.equal(overlay.hidden, false, "the dialog opens");

  // The navigation the dialog did not make: Back, a pasted hash, a link
  // elsewhere in the shell. All of them reach the shell as one event.
  documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  await settle();

  assert.equal(overlay.hidden, true, "the dialog closes with the route");
  assert.equal(
    byClass(root, "header-search")[0].getAttribute("aria-expanded"), "false",
    "and the trigger stops claiming it is expanded",
  );
});

test("repeated route changes with the dialog shut stay a no-op", async (t) => {
  const client = fixtureClient({});
  const { documentNode, root } = await mountShell(t, client);
  const overlay = byClass(root, "header-search-overlay")[0];

  assert.equal(overlay.hidden, true);
  for (let index = 0; index < 3; index += 1) {
    documentNode.defaultView.dispatchEvent(new Event("hashchange"));
  }
  await settle();
  assert.equal(overlay.hidden, true, "closing what is already shut changes nothing");
});

test("choosing a result still closes the dialog itself", async (t) => {
  const client = fixtureClient({});
  const { documentNode, root } = await mountShell(t, client);
  const overlay = byClass(root, "header-search-overlay")[0];

  byClass(root, "header-search")[0].dispatchEvent(new Event("click"));
  await settle();
  const input = byClass(root, "header-search-input")[0];
  input.value = "release";
  input.dispatchEvent(new Event("input"));
  await settleSearch();

  const result = byClass(root, "header-search-result")[0];
  assert.ok(result, "the fixture returns something to choose");
  result.dispatchEvent(new Event("click"));
  await settle();
  // The result handler closes it before navigating, so the route-change
  // listener is a second guarantee rather than the only one. Both firing is
  // a no-op, which is why this behaviour is unchanged.
  assert.equal(overlay.hidden, true, "the dialog closes on its own choosing path");
});

test("Escape still closes the dialog and returns focus to its opener", async (t) => {
  const client = fixtureClient({});
  const { documentNode, root } = await mountShell(t, client);
  const overlay = byClass(root, "header-search-overlay")[0];
  const trigger = byClass(root, "header-search")[0];

  trigger.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(overlay.hidden, false);

  const escape = new Event("keydown");
  escape.key = "Escape";
  escape.preventDefault = () => {};
  documentNode.defaultView.dispatchEvent(escape);
  await settle();

  assert.equal(overlay.hidden, true, "Escape still closes it");
  assert.equal(documentNode.activeElement, trigger, "and focus returns to the opener");
});
