import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  descendantText,
  overviewClient,
} from "./universe_ui_overview_view_test_support.mjs";

test("the Delivery summary keeps the engine's newest-first receipt order", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const runs = ["023", "022", "021", "020", "019", "018"].map((suffix) => ({
    id: `run-20260717-${suffix}`,
    project: "yoke",
    flow: "yoke-hosted-stage-no-ci-gate",
    target_env: "stage",
    current_stage: "complete",
    status: "succeeded",
    created_at: `2026-07-17T${suffix}:00:00Z`,
    stages: [{ name: "deploy", state: "complete" }],
  }));

  const mounted = mountUniverseApp(root, {
    client: overviewClient({ "deployment_runs.list": { rows: runs } }),
  });
  await settle();

  const receiptRows = byClass(root, "overview-delivery-row")
    .map((row) => row.children[0].children[0].textContent);
  assert.deepEqual(receiptRows, [
    "run-20260717-023", "run-20260717-022", "run-20260717-021",
    "run-20260717-020", "run-20260717-019",
  ]);
  const environments = byClass(root, "overview-environment-fact");
  assert.equal(environments.length, 1);
  assert.equal(
    environments[0].children[0].textContent,
    "yoke · stage",
  );
  assert.equal(environments[0].attributes.get("data-status"), "succeeded");
  assert.equal(byClass(environments[0], "ago")[0].textContent, "2026-07-17T023:00:00Z");
  mounted.unmount();
});

test("a doctor run that never ran reports the unavailable health state", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const client = overviewClient({ "doctor.last_run.get": { never_run: true } });

  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.equal(byClass(root, "stat").length, 0);
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("doctor has not run yet"));
  const doctor = byClass(root, "overview-section")[5];
  assert.equal(byClass(doctor, "panel-count")[0].textContent, "· not run");
  mounted.unmount();
});

test("Sessions keeps its full mode-shaped table and recently-ended region", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const sessionsTable = async (capabilities) => {
    const documentNode = new FakeDocument();
    documentNode.defaultView.location.hash = "#/overview?project=1";
    const root = documentNode.createElement("div");
    const client = overviewClient({
      "sessions.list": {
        rows: [
          {
            session_id: "s-ben", liveness: "active", execution_lane: "primary",
            mode: "charge", actor_id: 2, actor_kind: "human",
            actor_label: "ben", current_item: "YOK-9", project: "yoke",
            executor: "codex", model: "gpt-5.6-sol",
          },
          {
            session_id: "s-ci", liveness: "stale", execution_lane: "primary",
            mode: "wait", actor_id: 7, actor_kind: "system",
            actor_label: "preview-ci", current_item: null, project: "yoke",
            executor: "ci", model: "runner",
          },
          {
            session_id: "s-ended", liveness: "ended", execution_lane: "primary",
            mode: "wait", actor_id: 8, actor_kind: "system",
            actor_label: "old-worker", current_item: null, project: "yoke",
            executor: "codex", model: "gpt-5.6-sol",
          },
        ],
      },
    });
    const mounted = mountUniverseApp(root, {
      client, ...(capabilities ? { capabilities } : {}),
    });
    await settle();
    const table = byClass(root, "overview-sessions-table")[0];
    const headers = table.children[0].children[0].children.map(
      (header) => header.textContent,
    );
    const whoCells = byClass(table, "overview-who-cell").map(
      descendantText,
    );
    const identityChildren = byClass(table, "overview-session-identity").map(
      (identity) => identity.children.map((child) => child.className),
    );
    const endedRows = byClass(root, "overview-ended-session").map(
      (row) => row.textContent,
    );
    mounted.unmount();
    return { headers, whoCells, identityChildren, endedRows };
  };

  const localMode = await sessionsTable(null);
  assert.deepEqual(localMode.headers, [
    "Session", "Project", "Executor", "Model",
    "Lane", "Mode", "Age", "Claim",
  ]);
  assert.deepEqual(localMode.whoCells, []);
  assert.deepEqual(localMode.endedRows, ["s-ended"]);

  const actorMode = await sessionsTable({
    data: { portability: { mode: "self-host" } },
  });
  assert.equal(actorMode.headers[2], "Actor");
  assert.deepEqual(actorMode.whoCells, [
    "b ben #2", "preview-ci #7 machine",
  ]);
  assert.deepEqual(actorMode.identityChildren, [
    [
      "overview-session-avatar",
      "overview-session-actor-label",
      "overview-session-actor-id",
    ],
    [
      "overview-session-actor-label overview-session-machine-label",
      "overview-session-actor-id",
      "overview-session-machine-kind",
    ],
  ]);

  // Hosted mode uses mapped members; an unmapped machine never impersonates
  // either an account or its internal actor label.
  const memberMode = await sessionsTable({
    data: {
      portability: { mode: "hosted" },
      memberDirectory: { 2: "Ben Bauman" },
    },
  });
  assert.equal(memberMode.headers[2], "Member");
  assert.deepEqual(memberMode.whoCells, [
    "B Ben Bauman", "— machine",
  ]);
  assert.deepEqual(memberMode.identityChildren, [
    ["overview-session-avatar", "overview-session-member-label"],
    ["overview-session-unmapped", "overview-session-machine-kind"],
  ]);
});

test("Overview session Mode pills signal the directive, never liveness", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const rows = [
    ["charge", "stale"], ["resume", "stale"], ["wait", "active"],
    ["feed", "stale"], ["strategize", "active"], ["escalate", "active"],
  ].map(([mode, liveness], index) => ({
    session_id: `session-${index + 1}`,
    liveness,
    mode,
    project: "yoke",
    executor: "codex",
    model: "gpt-5.6-sol",
    execution_lane: "DARIUS",
    activity_at: "2026-07-26T12:00:00Z",
  }));
  const mounted = mountUniverseApp(root, {
    client: overviewClient({ "sessions.list": { rows } }),
  });
  await settle();

  const table = byClass(root, "overview-sessions-table")[0];
  assert.deepEqual(
    byClass(table, "pill").map((pill) => [
      pill.textContent,
      pill.className,
      pill.attributes.get("data-state"),
    ]),
    [
      ["charge", "pill run", "running"],
      ["resume", "pill run", "running"],
      ["wait", "pill idle", "waiting"],
      ["feed", "pill good", "active"],
      ["strategize", "pill good", "active"],
      ["escalate", "pill crit", "critical"],
    ],
  );
  mounted.unmount();
});

test("Events and Doctor use the prototype pulse and health hierarchies", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");

  const mounted = mountUniverseApp(root, { client: overviewClient() });
  await settle();

  assert.equal(byClass(root, "overview-pulse-row").length, 1);
  assert.equal(
    byClass(root, "overview-pulse-source")[0].textContent,
    "codex · desktop",
  );
  assert.equal(
    byClass(root, "overview-pulse-event")[0].textContent,
    "YokeFunctionCalled",
  );
  assert.equal(
    byClass(root, "overview-pulse-context")[0].textContent,
    "items.structured_field.replace · YOK-9",
  );
  assert.equal(byClass(root, "overview-doctor-rollup").length, 1);
  assert.equal(byClass(root, "overview-health-row").length, 1);
  assert.equal(
    byClass(root, "overview-health-check")[0].textContent,
    "HC-stale-migration",
  );
  const doctor = byClass(root, "overview-section")[5];
  assert.equal(byClass(doctor, "panel-count")[0].textContent, "· 2 warnings");
  mounted.unmount();
});

test("Overview CSS preserves responsive tables, theme tokens, and semantic signals", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_overview.css",
    import.meta.url,
  ), "utf8");
  for (const contract of [
    ".overview-mast-grid",
    ".overview-state-row[data-state=\"blocked\"]",
    ".overview-sparkline-line[data-series=\"code\"]",
    ".overview-table-wrap",
    ".overview-zen-queued::before",
    ".overview-zen-vision::before",
    ".overview-zen-vision-dot",
    ".overview-section-icon",
    ".overview-session-actor-id",
    ".overview-session-machine-kind",
    ".overview-pair",
    "@media (max-width: 720px)",
    "overflow-x: auto",
    "var(--yoke-surface)",
    "var(--yoke-ink)",
    "var(--yoke-accent)",
  ]) {
    assert.ok(css.includes(contract), contract);
  }
  assert.match(
    css,
    /\.overview-zen-dot\s*\{[^}]*width: 8px;[^}]*height: 8px;[^}]*background: var\(--yoke-accent\);/s,
  );
  assert.match(
    css,
    /\.overview-zen-vision-dot\s*\{[^}]*left: 50%;[^}]*border: 1\.6px solid var\(--yoke-muted\);[^}]*background: var\(--yoke-bg\);/s,
  );
  assert.match(
    css,
    /\.overview-section-icon\s*\{[^}]*color: var\(--yoke-accent\);[^}]*font-size: 14px;/s,
  );
});
