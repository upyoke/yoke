// The Overview holds its all-project reads for the lifetime of one mount: a
// project-selection change re-renders the scoped panels from held data with no
// new function calls and without tearing down the activation stack, the
// picker, or the page head.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { multiProjectOverviewClient } from "./universe_ui_overview_view_test_support.mjs";

const sessionIds = (root) =>
  byClass(root, "overview-session-id").map(cellText);
const runIds = (root) => byClass(root, "overview-run-id").map(cellText);
const openHrefs = (root) =>
  byClass(root, "overview-open").map((link) => link.href);
const activeCount = (root) =>
  byClass(root, "overview-state-value")[0].textContent;
const callCount = (client, fn) =>
  client.requests.filter((request) => request.function === fn).length;

test("a project-selection change re-renders from held data with zero new reads", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const client = multiProjectOverviewClient();

  const mounted = mountUniverseApp(root, { client });
  await settle();

  // Mount holds every read once — including one read per project for the
  // per-project fan-out reads (vitals/events/doctor/strategy) — so a later
  // scope change never needs to fetch.
  const before = client.requests.length;
  assert.equal(callCount(client, "overview.activation.get"), 1);
  assert.equal(callCount(client, "overview.vitals.get"), 2);

  // At project=1 the held universe reads are filtered to the yoke rows, and
  // the masthead is projected from the held per-project vitals.
  assert.deepEqual(sessionIds(root), ["s-yoke"]);
  assert.deepEqual(runIds(root), ["run-yoke"]);
  assert.equal(activeCount(root), "3");
  assert.deepEqual(openHrefs(root), [
    "#/strategy?project=1", "#/items?project=1", "#/sessions?project=1",
    "#/deployments?project=1",   ]);

  const activationHost = byClass(root, "activation-host")[0];
  const activationStack = byClass(root, "activation-stack")[0];
  const scopeBar = byClass(root, "scope-bar")[0];
  const pageHead = byClass(root, "page-head")[0];

  const navigate = async (hash) => {
    windowNode.location.hash = hash;
    windowNode.dispatchEvent(new Event("hashchange"));
    await settle();
  };

  // Switch to project 2: zero new reads, held data re-filtered to beta.
  await navigate("#/overview?project=2");
  assert.equal(client.requests.length, before, "no refetch on scope change");
  assert.deepEqual(sessionIds(root), ["s-beta"]);
  assert.deepEqual(runIds(root), ["run-beta"]);
  assert.equal(activeCount(root), "1");
  assert.deepEqual(openHrefs(root), [
    "#/strategy?project=2", "#/items?project=2", "#/sessions?project=2",
    "#/deployments?project=2",   ]);

  // The activation stack, picker, and page head are the same nodes — no full
  // route render ran, so onboarding never reloaded.
  assert.equal(byClass(root, "activation-host")[0], activationHost);
  assert.equal(byClass(root, "activation-stack")[0], activationStack);
  assert.equal(byClass(root, "scope-bar")[0], scopeBar);
  assert.equal(byClass(root, "page-head")[0], pageHead);
  assert.equal(callCount(client, "overview.activation.get"), 1);

  // Switch to All: still zero new reads; every project's held rows show, the
  // masthead sums per-project vitals, and the projectless session surfaces.
  await navigate("#/overview?project=all");
  assert.equal(client.requests.length, before, "no refetch widening to All");
  assert.deepEqual(sessionIds(root).sort(), ["s-beta", "s-nil", "s-yoke"]);
  assert.deepEqual(runIds(root).sort(), ["run-beta", "run-yoke"]);
  assert.equal(activeCount(root), "4");
  assert.deepEqual(openHrefs(root), [
    "#/strategy", "#/items", "#/sessions",
    "#/deployments",   ]);
  assert.equal(byClass(root, "activation-host")[0], activationHost);
  mounted.unmount();
});

test("a scope chip toggle repaints in place and tracks the selection", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const client = multiProjectOverviewClient();

  const mounted = mountUniverseApp(root, { client });
  await settle();
  const before = client.requests.length;

  const chip = (label) =>
    byClass(root, "scope-chip").find((node) => node.textContent === label);
  const chipState = () =>
    byClass(root, "scope-chip").map((node) => [
      node.textContent, node.classList.contains("on"),
    ]);

  // Adding the beta chip widens to both projects: no refetch, both projects'
  // held rows render, and the chips reflect the selection in place.
  chip("beta").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(client.requests.length, before);
  assert.deepEqual(sessionIds(root).sort(), ["s-beta", "s-yoke"]);
  assert.deepEqual(chipState(), [["All", false], ["yoke", true], ["beta", true]]);

  // Removing the yoke chip narrows to beta only — still no refetch.
  chip("yoke").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(client.requests.length, before);
  assert.deepEqual(sessionIds(root), ["s-beta"]);
  assert.deepEqual(chipState(), [["All", false], ["yoke", false], ["beta", true]]);
  assert.equal(documentNode.defaultView.location.hash, "#/overview?project=2");
  mounted.unmount();
});

test("one project's failed read never poisons a scope that excludes it", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  const windowNode = documentNode.defaultView;
  windowNode.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  // Project 2's per-project fan-out reads fail at mount.
  const client = multiProjectOverviewClient({ failProject: "2" });

  const mounted = mountUniverseApp(root, { client });
  await settle();
  const before = client.requests.length;

  const syncText = () => byClass(root, "overview-sync")[0].textContent;
  const navigate = async (hash) => {
    windowNode.location.hash = hash;
    windowNode.dispatchEvent(new Event("hashchange"));
    await settle();
  };

  // Scoped to the healthy project 1: no panel shows a read error and the
  // masthead projects project 1's held vitals.
  assert.equal(byClass(root, "error").length, 0);
  assert.equal(activeCount(root), "3");
  assert.doesNotMatch(syncText(), /state and momentum read unavailable/);

  // Scoped to the failed project 2: the per-project panels surface the error
  // and the masthead reports unavailable — but still no refetch.
  await navigate("#/overview?project=2");
  assert.equal(client.requests.length, before);
  assert.ok(byClass(root, "error").length > 0, "failed scope shows the error");
  assert.match(syncText(), /state and momentum read unavailable/);

  // Back to project 1: the healthy held data re-renders cleanly — the earlier
  // failure never stuck — and still no refetch.
  await navigate("#/overview?project=1");
  assert.equal(client.requests.length, before);
  assert.equal(byClass(root, "error").length, 0);
  assert.equal(activeCount(root), "3");
  assert.doesNotMatch(syncText(), /state and momentum read unavailable/);
  mounted.unmount();
});
