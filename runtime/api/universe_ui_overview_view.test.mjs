import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

import { overviewClient } from "./universe_ui_overview_view_test_support.mjs";

test("Overview is no longer a stub: it composes the six section reads", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const client = overviewClient();

  const mounted = mountUniverseApp(root, { client });
  await settle();

  // The coming-soon stub is gone; the six summary panels stand in its place.
  assert.equal(byClass(root, "stub-panel").length, 0);
  assert.deepEqual(
    byClass(root, "overview-section-icon").map((node) => node.textContent),
    ["❖", "⚡", "◈", "⬈", "≋", "♥"],
  );
  assert.deepEqual(
    byClass(root, "overview-section-title").map((node) => node.textContent),
    ["Strategy", "Frontier", "Sessions", "Delivery", "Events", "Doctor"],
  );
  assert.equal(byClass(root, "overview-section-heading").length, 6);
  assert.match(
    allNodes(root).map((node) => node.textContent).join(" "),
    /2 runnable · 1 blocked/,
  );
  assert.doesNotMatch(
    allNodes(root).map((node) => node.textContent).join(" "),
    /workflow type/,
  );
  assert.match(
    allNodes(root).map((node) => node.textContent).join(" "),
    /Your Yoke universe at a glance/,
  );

  // The prototype's hierarchy is present: one signal masthead and a compact
  // final row for pulse + health.
  assert.equal(byClass(root, "overview-masthead").length, 1);
  const finalPair = byClass(root, "overview-pair");
  assert.equal(finalPair.length, 1);
  assert.equal(byClass(finalPair[0], "overview-section").length, 2);
  assert.deepEqual(
    byClass(root, "overview-section-detail").map((node) => node.textContent),
    [
      "where this universe has been, and where VISION points it",
      "what can run now, and why",
      "this machine",
      "what is shipping, and where it stands",
      "the pulse · newest first",
      "the floor · invariants that hold",
    ],
  );
  assert.deepEqual(
    byClass(root, "overview-section").map((panel) =>
      byClass(panel, "panel-count")[0]?.textContent || null),
    [
      null,
      "· 2 runnable · 1 blocked",
      "· 1 live",
      "· 1 runs",
      "· 1",
      "· 2 warnings",
    ],
  );
  assert.equal(byClass(root, "raw-toggle").length, 6);

  // Each section replays the read its full screen runs, plus exactly one
  // Overview-owned read: the activation-module derivation.
  const called = new Set(client.requests.map((request) => request.function));
  for (const functionId of [
    "frontier.list", "sessions.list", "strategy.doc.list",
    "deployment_runs.list", "events.query.run", "doctor.last_run.get",
    "overview.activation.get", "overview.vitals.get",
  ]) {
    assert.ok(called.has(functionId), functionId);
  }

  // Every section links out to its full screen, carrying the held scope.
  const openLinks = byClass(root, "overview-open").map((link) => link.href);
  assert.deepEqual(openLinks, [
    "#/strategy?project=1", "#/frontier?project=1", "#/sessions?project=1",
    "#/delivery?project=1", "#/events?project=1", "#/doctor?project=1",
  ]);
  mounted.unmount();
});

test("the Overview jump strip maps and scrolls to all six summaries", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");

  const mounted = mountUniverseApp(root, { client: overviewClient() });
  await settle();

  const jumpStrip = byClass(root, "overview-jumps");
  assert.equal(jumpStrip.length, 1);
  assert.equal(jumpStrip[0].tagName, "NAV");
  assert.equal(jumpStrip[0].attributes.get("aria-label"), "Overview sections");
  const jumps = byClass(jumpStrip[0], "overview-jump");
  assert.deepEqual(jumps.map((jump) => jump.textContent), [
    "❖ Strategy", "⚡ Frontier", "◈ Sessions",
    "⬈ Delivery", "≋ Events", "♥ Doctor",
  ]);
  assert.deepEqual(jumps.map((jump) => jump.attributes.get("aria-controls")), [
    "overview-strategy", "overview-frontier", "overview-sessions",
    "overview-delivery", "overview-events", "overview-doctor",
  ]);

  const panels = byClass(root, "overview-section");
  assert.equal(panels.length, 6);
  let scrollOptions = null;
  panels[3].scrollIntoView = (options) => { scrollOptions = options; };
  jumps[3].dispatchEvent(new Event("click"));
  assert.deepEqual(scrollOptions, { behavior: "smooth", block: "start" });
  mounted.unmount();
});

test("the masthead projects state and 120-day momentum as distinct signals", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");

  const mounted = mountUniverseApp(root, { client: overviewClient() });
  await settle();

  assert.equal(byClass(root, "stat").length, 0);
  const stateRows = byClass(root, "overview-state-row");
  assert.deepEqual(stateRows.map((node) => [
    byClass(node, "overview-state-icon")[0].textContent,
    byClass(node, "overview-state-label")[0].textContent,
    byClass(node, "overview-state-value")[0].textContent,
  ]), [
    ["🎫", "Active", "3"], ["💧", "Pipeline", "2"],
    ["🌱", "Backlog", "4"], ["⛔", "Blocked", "1"],
    ["🧊", "Frozen", "0"], ["✅", "Done", "2,828"],
  ]);
  assert.deepEqual(
    stateRows.map((node) => byClass(node, "overview-state-meter")[0]
      .children[0].style.width),
    ["2%", "2%", "2%", "2%", "0%", "100%"],
  );
  assert.equal(byClass(root, "overview-momentum-total").length, 0);
  assert.deepEqual(
    byClass(root, "overview-sparkline-line").map(
      (line) => line.attributes.get("data-series"),
    ),
    ["activity", "code", "issues", "strategy"],
  );
  assert.equal(
    byClass(root, "overview-streak")[0].textContent,
    "🔥🔥 2d streak (40.00%)",
  );
  assert.match(
    byClass(root, "overview-sync")[0].textContent,
    /momentum window 120 days · last sync unavailable/,
  );
  mounted.unmount();
});

test("Strategy and Frontier preserve the prototype anatomy with truthful facts", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");

  const mounted = mountUniverseApp(root, { client: overviewClient() });
  await settle();

  assert.equal(byClass(root, "overview-zen-row").length, 1);
  assert.equal(byClass(root, "overview-zen-past").length, 1);
  assert.equal(byClass(root, "overview-zen-now")[0].textContent, "🔸");
  assert.equal(byClass(root, "overview-zen-queued").length, 1);
  assert.equal(byClass(root, "overview-zen-vision").length, 2);
  assert.equal(byClass(root, "overview-zen-dot").length, 5);
  const visionDots = byClass(root, "overview-zen-vision-dot");
  assert.equal(visionDots.length, 2);
  assert.equal(
    visionDots.every((dot) =>
      dot.parentNode.classList.contains("overview-zen-vision")),
    true,
  );
  assert.deepEqual(
    byClass(root, "overview-zen-label").map((node) => node.textContent),
    ["registry", "items"],
  );
  assert.equal(
    byClass(root, "overview-zen-queued")[0].children[0].textContent,
    "3 queued",
  );
  assert.deepEqual(
    byClass(root, "overview-zen-vision").map(
      (node) => byClass(node, "overview-zen-zone-label")[0].textContent,
    ),
    ["web steering", "multi-actor"],
  );
  const docBadge = byClass(root, "overview-doc-badge")[0];
  assert.equal(docBadge.href, "#/strategy/MISSION?project=1");
  assert.equal(byClass(root, "overview-doc-total")[0].textContent, "1 doc");

  const frontierTable = byClass(root, "overview-frontier-table")[0];
  assert.deepEqual(
    frontierTable.children[0].children[0].children.map(
      (header) => header.textContent,
    ),
    ["#", "Item", "Project", "Progress", "Why it can run", "Run in your harness"],
  );
  assert.equal(byClass(root, "overview-ready-row").length, 2);
  assert.deepEqual(
    byClass(root, "overview-rank").map((node) => node.textContent),
    ["1", "2"],
  );
  const readyRow = byClass(root, "overview-ready-row")[0];
  assert.equal(readyRow.attributes.get("role"), "link");
  readyRow.dispatchEvent(new Event("click"));
  assert.equal(documentNode.defaultView.location.hash, "#/frontier?project=1");
  assert.deepEqual(
    byClass(root, "overview-command").map((node) => node.textContent),
    ["yoke advance YOK-9", "yoke conduct YOK-8"],
  );
  assert.equal(
    byClass(root, "overview-command").every((node) => node.tagName === "CODE"),
    true,
  );
  assert.equal(byClass(root, "overview-blocked-row").length, 1);
  assert.equal(byClass(root, "overview-age-cells")[0].children.length, 3);
  assert.match(
    byClass(root, "overview-workflow-counts")[0].textContent,
    /issue 3/,
  );
  mounted.unmount();
});

test("Overview keeps the prototype's six-document and seven-session summary density", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const docs = Array.from({ length: 17 }, (_, index) => ({
    slug: `DOC-${String(index + 1).padStart(2, "0")}`,
    title: `Document ${index + 1}`,
    updated_at: `2026-07-${String(26 - index).padStart(2, "0")}T12:00:00Z`,
    execution_state: index === 0 ? "claimed" : "available",
  }));
  const sessions = Array.from({ length: 8 }, (_, index) => ({
    session_id: `session-${index + 1}`,
    liveness: "active",
    project: "yoke",
    executor: "codex",
    model: "gpt-5.6-sol",
    execution_lane: "DARIUS",
    mode: "charge",
    actor_id: 2,
    actor_kind: "human",
    activity_at: "2026-07-26T12:00:00Z",
  }));

  const mounted = mountUniverseApp(root, {
    client: overviewClient({
      "strategy.doc.list": { docs },
      "sessions.list": { rows: sessions },
    }),
  });
  await settle();

  assert.equal(byClass(root, "overview-doc-badge").length, 6);
  assert.equal(
    byClass(root, "overview-doc-total")[0].textContent,
    "17 docs · 1 claimed",
  );
  assert.equal(byClass(root, "overview-session-row").length, 7);
  mounted.unmount();
});

test("the activation stack renders above the scope picker", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");

  const mounted = mountUniverseApp(root, { client: overviewClient() });
  await settle();

  // The onboarding (activation) stack lives in the view-owned above-scope
  // host, so it sits above the project picker rather than below it.
  const aboveScope = byClass(root, "view-above-scope");
  assert.equal(aboveScope.length, 1);
  assert.equal(byClass(aboveScope[0], "activation-host").length, 1);

  const order = allNodes(root);
  const activationIndex = order.findIndex(
    (node) => node.classList.contains("activation-host"),
  );
  const pickerIndex = order.findIndex(
    (node) => node.classList.contains("scope-bar"),
  );
  assert.ok(activationIndex >= 0 && pickerIndex >= 0);
  assert.ok(
    activationIndex < pickerIndex,
    "activation host must render before the scope picker",
  );
  mounted.unmount();
});
