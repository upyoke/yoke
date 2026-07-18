import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

// A one-project universe that answers every read the Overview composes. Rows
// are shaped like the engine's, so the summary panels render the same columns
// their full screens do.
function overviewClient(overrides = {}) {
  const requests = [];
  const answers = {
    "frontier.list": {
      ready_rows: [
        {
          item_id: "YOK-9", item_type: "issue", project: "yoke",
          status: "planned", priority: "high", rank: 1,
          next_step: "advance", run_command: "yoke advance YOK-9",
          why_ready: "no blockers",
        },
        {
          item_id: "YOK-8", item_type: "issue", project: "yoke",
          status: "refined-idea", priority: "medium", rank: 2,
          next_step: "conduct", run_command: "yoke conduct YOK-8",
          why_ready: "claims free",
        },
      ],
      blocked_rows: [
        {
          item_id: "YOK-7", project: "yoke", blocking_item: "YOK-9",
          gate_point: "activation", why: "waits for YOK-9",
        },
      ],
    },
    "sessions.list": {
      rows: [
        {
          session_id: "s-run", liveness: "active", execution_lane: "primary",
          mode: "charge", actor_id: 2, actor_kind: "human", actor_label: "Ben",
          claims: [], current_item: "YOK-9", activity_at: "now",
        },
      ],
    },
    "strategy.doc.list": {
      docs: [{
        slug: "MISSION", title: "why", updated_by: "ben",
        updated_at: "today", bytes: 10, archived: false,
      }],
    },
    "deployment_runs.list": {
      rows: [{
        id: "run-1", flow: "yoke-hosted-stage", target_env: "stage",
        current_stage: "complete", status: "succeeded", created_at: "1h",
      }],
    },
    "events.query.run": {
      rows: [{
        created_at: "30s", event_name: "YokeFunctionCalled",
        event_kind: "function", severity: "info", actor_id: "codex",
      }],
    },
    "doctor.last_run.get": {
      never_run: false, ran_at: "today", total: 44, pass_count: 42,
      warn_count: 2, fail_count: 0,
      results: [
        { hc: "HC-title-length", name: "titles", severity: "pass" },
        { hc: "HC-stale-migration", name: "migrations", severity: "warn" },
      ],
    },
    ...overrides,
  };
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: { rows: [{ id: 1, slug: "yoke", name: "Yoke" }] },
          },
        };
      }
      if (request.function in answers) {
        return { status: 200, envelope: { success: true, result: answers[request.function] } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

function panelTitles(root) {
  return byClass(root, "panel-header")
    .map((header) => byClass(header, "panel-count").length
      ? header.children[0].children[0].textContent
      : header.children[0].textContent);
}

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
  const titles = allNodes(root)
    .filter((node) => node.tagName === "H2")
    .map((node) => node.textContent);
  assert.deepEqual(titles, [
    "Strategy", "Frontier", "Sessions", "Delivery", "Events", "Doctor",
  ]);

  // Each section replays the read its full screen runs — no new function ids.
  const called = new Set(client.requests.map((request) => request.function));
  for (const functionId of [
    "frontier.list", "sessions.list", "strategy.doc.list",
    "deployment_runs.list", "events.query.run", "doctor.last_run.get",
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

test("the stat tiles fill from the reads, and never invent a number", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");

  const mounted = mountUniverseApp(root, { client: overviewClient() });
  await settle();

  // Tiles read: ready (2 ready_rows), live sessions (1), blocked (1
  // blocked_row), checks passing (doctor pass_count 42).
  const tiles = byClass(root, "stat");
  assert.deepEqual(
    tiles.map((tile) => byClass(tile, "n")[0].textContent),
    ["2", "1", "1", "42"],
  );
  assert.deepEqual(
    tiles.map((tile) => byClass(tile, "l")[0].textContent),
    ["ready to run", "live sessions", "blocked", "checks passing"],
  );
  mounted.unmount();
});

test("the Delivery summary keeps the engine's newest-first receipt order", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const runs = ["023", "022", "021", "020", "019", "018"].map((suffix) => ({
    id: `run-20260717-${suffix}`,
    flow: "yoke-hosted-stage-no-ci-gate",
    target_env: "stage",
    current_stage: "complete",
    status: "succeeded",
    created_at: `2026-07-17T${suffix}:00:00Z`,
  }));

  const mounted = mountUniverseApp(root, {
    client: overviewClient({ "deployment_runs.list": { rows: runs } }),
  });
  await settle();

  const deliveryPanel = byClass(root, "panel")[3];
  const receiptRows = allNodes(deliveryPanel)
    .filter((node) => node.tagName === "TR")
    .slice(1)
    .map((row) => cellText(row.children[0]));
  assert.deepEqual(receiptRows, [
    "run-20260717-023", "run-20260717-022", "run-20260717-021",
    "run-20260717-020", "run-20260717-019",
  ]);
  mounted.unmount();
});

test("a doctor run that never ran leaves the checks tile an em dash", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const client = overviewClient({ "doctor.last_run.get": { never_run: true } });

  const mounted = mountUniverseApp(root, { client });
  await settle();

  // The other tiles resolve; the checks tile has no honest number to show.
  const checksTile = byClass(root, "stat")[3];
  assert.equal(byClass(checksTile, "l")[0].textContent, "checks passing");
  assert.equal(byClass(checksTile, "n")[0].textContent, "—");
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("doctor has not run yet"));
  mounted.unmount();
});

// The Sessions summary's who-column is the one place the screen changes by
// mode: it names the actor by default, and the member the host maps it to
// wherever accounts exist.
test("the Sessions summary names the actor, and a member directory renames it", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const sessionsSummaryCells = async (capabilities) => {
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.hash = "#/overview?project=1";
    const root = documentNode.createElement("div");
    const client = overviewClient({
      "sessions.list": {
        rows: [
          {
            session_id: "s-ben", liveness: "active", execution_lane: "primary",
            mode: "charge", actor_id: 2, actor_kind: "human",
            actor_label: "ben", current_item: "YOK-9",
          },
          {
            session_id: "s-ci", liveness: "stale", execution_lane: "primary",
            mode: "wait", actor_id: 7, actor_kind: "system",
            actor_label: "preview-ci", current_item: null,
          },
        ],
      },
    });
    const mounted = mountUniverseApp(root, {
      client, ...(capabilities ? { capabilities } : {}),
    });
    await settle();
    // The Sessions panel is the third; read its header label and who-cells.
    const sessionsPanel = byClass(root, "panel")[2];
    const header = allNodes(sessionsPanel)
      .filter((node) => node.tagName === "TH")
      .map((node) => node.textContent);
    const whoCells = allNodes(sessionsPanel)
      .filter((node) => node.tagName === "TR")
      .slice(1)
      .map((tr) => cellText(tr.children[1]));
    mounted.unmount();
    return { header, whoCells };
  };

  // No directory (local / self-hosted): the column is the engine's actor.
  const actorMode = await sessionsSummaryCells(null);
  assert.equal(actorMode.header[1], "actor");
  assert.deepEqual(actorMode.whoCells, ["ben", "preview-ci · system"]);

  // A host that names accounts (hosted): the column becomes the member it
  // maps to, and a machine actor the directory does not name keeps its actor
  // identity rather than borrowing someone else's.
  const memberMode = await sessionsSummaryCells({
    data: { memberDirectory: { 2: "Ben Bauman" } },
  });
  assert.equal(memberMode.header[1], "member");
  assert.deepEqual(memberMode.whoCells, ["Ben Bauman", "preview-ci · system"]);
});
