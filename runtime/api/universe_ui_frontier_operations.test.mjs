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
import { workbenchClient } from "./universe_ui_workbench_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function mountAt(hash, client) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { mounted, root };
}

test("Shipping shows every run in its window, newest first", async (t) => {
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
  const { mounted, root } = await mountAt("#/shipping?project=1", workbenchClient({
    "deployment_runs.list": { rows: runs },
  }));

  // The 24-hour run window already bounds the page; a second sample cap on
  // top of it hid runs that were genuinely in flight.
  assert.deepEqual(
    byClass(root, "shipping-run-id").map((node) => node.textContent),
    runs.map((row) => row.id),
  );
  assert.equal(byClass(root, "shipping-run-card").length, 10);
  // No band, and so no count beside a page title.
  assert.equal(byClass(root, "work-band").length, 0);
  mounted.unmount();
});

test("a waiting run names the project deploy lock holding it", async (t) => {
  stubFetch(t);
  const holder = {
    session_id: "s-lock", liveness: "active", project: "yoke", project_id: 1,
    executor: "claude-cli", execution_lane: "delivery",
    activity_at: new Date().toISOString(),
    holdings: {
      current: [{
        holding_kind: "coordination", target_kind: "deploy_serialization",
        lease_key: "DEPLOY:yoke", target: "DEPLOY:yoke",
      }],
      previous: [], previous_remainder: 0,
    },
  };
  const { mounted, root } = await mountAt("#/shipping?project=1", workbenchClient({
    "sessions.list": { rows: [holder] },
  }));

  const locks = byClass(root, "shipping-run-lock");
  // The executing run carries it; the finished one does not, because
  // nothing a terminal run is waiting on can still apply to it.
  assert.equal(locks.length, 1);
  assert.match(
    byClass(locks[0], "shipping-run-lock-label")[0].textContent,
    /Deploy lock · yoke · project-wide/,
  );
  assert.equal(byClass(locks[0], "item-claimant-mini").length, 1);
  mounted.unmount();
});

test("Active membership follows live claims, not lifecycle status", async (t) => {
  stubFetch(t);
  // Three sessions focused on the same item: one holds it and is answering,
  // one holds nothing, and one has ended. Only the first makes it Active.
  const now = Date.now();
  const base = (sessionId, liveness, secondsAgo) => ({
    session_id: sessionId, liveness,
    project: "yoke", project_id: 1,
    executor: "codex", model: "gpt-5.6-sol",
    execution_lane: "implementation",
    activity_at: new Date(now - secondsAgo * 1000).toISOString(),
  });
  const holding = {
    ...base("s-active", "active", 0),
    current_item: "YOK-9",
    current_item_title: "Ship typed workflows",
    claims: [{ target_kind: "item", public_ref: "YOK-9", target: "YOK-9" }],
    holdings: { current: [], previous: [], previous_remainder: 0 },
  };
  const ended = {
    ...base("s-ended", "ended", 120),
    claims: [{ target_kind: "item", public_ref: "YOK-7", target: "YOK-7" }],
  };
  const { mounted, root } = await mountAt("#/frontier?project=1", workbenchClient({
    "sessions.list": {
      rows: [holding, base("s-idle", "active", 60), ended],
    },
  }));

  const active = byClass(root, "work-band-active")[0];
  assert.deepEqual(
    byClass(active, "work-item-card-ref").map((node) => node.textContent),
    ["YOK-9"],
  );
  // The ended session's claim does not hold YOK-7 out of its own band: a
  // frozen item is Waiting because it is frozen, not because of that claim.
  const waiting = byClass(root, "work-band-waiting")[0];
  assert.deepEqual(
    byClass(waiting, "work-item-card-ref").map((node) => node.textContent),
    ["YOK-7"],
  );
  assert.deepEqual(
    byClass(waiting, "item-status-pill").map(
      (node) => node.children.at(-1).textContent,
    ),
    ["Frozen"],
  );
  mounted.unmount();
});

test("the final responsive layer caps grids and owns compact behavior", () => {
  const staticUrl = "../../packages/yoke-core/src/yoke_core/ui/static/";
  const responsive = readFileSync(new URL(
    `${staticUrl}universe_responsive.css`, import.meta.url,
  ), "utf8");
  // Cards fill their row; only the minimum is fixed, and it differs by what
  // the card has to hold.
  assert.match(
    responsive,
    /minmax\(min\(100%, var\(--yoke-card-track-min\)\), 1fr\)/,
  );
  assert.match(responsive, /--yoke-card-track-min: 300px/);
  assert.match(
    responsive, /\.strategy-doc-grid \{\s*--yoke-card-track-min: 280px/,
  );
  assert.match(
    responsive, /\.machines-grid \{\s*--yoke-card-track-min: 440px/,
  );
  for (const contract of [
    "@media (max-width: 1180px)",
    "@media (max-width: 980px)",
    "@media (max-width: 640px)",
    "@media (hover: none)",
    ".shell.side-open > .sidenav",
    ".header-search-overlay",
    ".work-card-grid",
  ]) assert.ok(responsive.includes(contract), contract);
  assert.ok(!responsive.includes("minmax(268px, 1fr)"));
});
