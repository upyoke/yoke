import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import { overviewClient } from "./universe_ui_overview_view_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function renderOverview(client) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { mounted, root };
}

test("Shipping keeps newest-first run cards and caps the visible set", async (t) => {
  stubFetch(t);
  const runs = Array.from({ length: 10 }, (_, index) => ({
    id: `run-${String(10 - index).padStart(2, "0")}`,
    project: "yoke",
    flow: "release",
    target_environment: "stage",
    status: "executing",
    created_at: new Date(Date.now() - index * 60_000).toISOString(),
    stages: [{ name: "deploy", state: "active" }],
  }));
  const { mounted, root } = await renderOverview(overviewClient({
    "deployment_runs.list": { rows: runs },
  }));

  assert.deepEqual(
    byClass(root, "overview-run-id").map((node) => node.textContent),
    runs.slice(0, 8).map((row) => row.id),
  );
  assert.equal(byClass(root, "overview-run-card").length, 8);
  const shipping = byClass(root, "overview-band-shipping")[0];
  assert.equal(byClass(shipping, "overview-band-count")[0].textContent, "10");
  mounted.unmount();
});

test("Active reuses full session cards and excludes ended sessions", async (t) => {
  stubFetch(t);
  const rows = [
    ["s-active", "active", "charge", null],
    ["s-parked", "stale", "parked", "waiting on YOK-7"],
    ["s-ended", "ended", "wait", null],
  ].map(([session_id, liveness, mode, quiet_reason]) => ({
    session_id, liveness, mode, quiet_reason,
    project: "yoke", project_id: 1,
    executor: "codex", model: "gpt-5.6-sol",
    execution_lane: "implementation",
    activity_at: new Date().toISOString(),
  }));
  const { mounted, root } = await renderOverview(overviewClient({
    "sessions.list": { rows },
  }));

  assert.deepEqual(
    byClass(root, "session-card").map(
      (node) => node.attributes.get("data-session-id"),
    ),
    ["s-active", "s-parked"],
  );
  assert.equal(byClass(root, "session-model-line").length, 2);
  const badge = byClass(root, "session-reason-badge")
    .find((node) => !node.hidden);
  assert.equal(badge.title, "waiting on YOK-7");
  mounted.unmount();
});

test("the final responsive layer caps grids and owns compact behavior", () => {
  const staticUrl = "../../packages/yoke-core/src/yoke_core/ui/static/";
  const overview = readFileSync(new URL(
    `${staticUrl}universe_overview.css`, import.meta.url,
  ), "utf8");
  const responsive = readFileSync(new URL(
    `${staticUrl}universe_responsive.css`, import.meta.url,
  ), "utf8");
  assert.match(overview, /minmax\(268px, 360px\)/);
  for (const contract of [
    "@media (max-width: 1180px)",
    "@media (max-width: 980px)",
    "@media (max-width: 640px)",
    "@media (hover: none)",
    ".shell.side-open > .sidenav",
    ".header-search-overlay",
    ".overview-card-grid",
  ]) assert.ok(responsive.includes(contract), contract);
  assert.ok(!responsive.includes("minmax(268px, 1fr)"));
});
