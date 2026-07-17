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

// One universe whose doctor journal answers with the given result, so each
// state the view must render honestly is one doubled read away.
function doctorClient(lastRunResult) {
  const requests = [];
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
      if (request.function === "doctor.last_run.get") {
        return { status: 200, envelope: { success: true, result: lastRunResult } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountDoctor(hash, lastRunResult) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const client = doctorClient(lastRunResult);
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { root, client, mounted };
}

test("a completed run renders the fact line, stat tiles, and pilled checks", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const { root, client, mounted } = await mountDoctor("#/doctor?project=1", {
    never_run: false,
    ran_at: "2026-07-16T00:00:00Z",
    scope: "quick",
    project: "yoke",
    pass_count: 2,
    warn_count: 1,
    fail_count: 1,
    total: 4,
    results: [
      { hc: "HC-a", name: "alpha", severity: "PASS", detail: "" },
      { hc: "HC-b", name: "beta", severity: "WARN", detail: "w" },
      { hc: "HC-c", name: "gamma", severity: "FAIL", detail: "f" },
      { hc: "HC-d", name: "delta", severity: "SKIP", detail: "" },
    ],
    truncated: false,
  });

  // One project in scope: the read carries that project, nothing more.
  assert.deepEqual(
    client.requests.find((request) => request.function === "doctor.last_run.get"),
    { function: "doctor.last_run.get", payload: { project: "1" } },
  );

  const factLine = byClass(root, "fact-line")[0];
  assert.equal(factLine.textContent, "last run 2026-07-16T00:00:00Z · scope quick");

  // Stat tiles in declared order: total, passing, warnings, failing.
  assert.deepEqual(
    byClass(root, "n").map((node) => node.textContent),
    ["4", "2", "1", "1"],
  );

  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "HC-a", "alpha", "PASS",
    "HC-b", "beta", "WARN",
    "HC-c", "gamma", "FAIL",
    "HC-d", "delta", "SKIP",
  ]);
  // The check column wears the machine-name dress; results color through
  // the semantic pill families (PASS good, WARN warn, FAIL crit, SKIP idle).
  const monoCells = allNodes(root)
    .filter((node) => node.tagName === "TD" && node.classList.contains("mono"));
  assert.deepEqual(monoCells.map((node) => node.textContent), [
    "HC-a", "HC-b", "HC-c", "HC-d",
  ]);
  assert.deepEqual(
    byClass(root, "pill").map((pill) => pill.className),
    ["pill good", "pill warn", "pill crit", "pill idle"],
  );
  mounted.unmount();
});

test("a universe whose doctor never ran shows the command to run, as text", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const { root, client, mounted } = await mountDoctor("#/doctor", {
    never_run: true,
  });

  // The "all" default reads unfiltered.
  assert.deepEqual(
    client.requests.find((request) => request.function === "doctor.last_run.get"),
    { function: "doctor.last_run.get", payload: {} },
  );
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("doctor has not run yet"));
  // Copyable command text: a <code> element, never a button.
  const code = allNodes(root).find((node) => node.tagName === "CODE");
  assert.ok(code);
  assert.equal(code.textContent, "yoke doctor run --quick");
  assert.ok(!allNodes(root).some(
    (node) => node.tagName === "BUTTON" &&
      (node.textContent || "").includes("doctor run"),
  ));
  mounted.unmount();
});

test("a journal-truncated run keeps its honesty: dashes and the rerun hint", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const { root, mounted } = await mountDoctor("#/doctor", {
    never_run: false,
    ran_at: "2026-07-15T00:00:00Z",
    scope: null,
    project: null,
    pass_count: null,
    warn_count: null,
    fail_count: null,
    total: null,
    results: [],
    truncated: true,
  });

  assert.equal(
    byClass(root, "fact-line")[0].textContent,
    "last run 2026-07-15T00:00:00Z",
  );
  // Unrecoverable counts render as dashes, never invented zeros.
  assert.deepEqual(
    byClass(root, "n").map((node) => node.textContent),
    ["—", "—", "—", "—"],
  );
  const text = allNodes(root).map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes(
    "detail truncated in the journal; run doctor again for a fresh report",
  ));
  // No checks table renders for a report the journal no longer holds.
  assert.ok(!allNodes(root).some((node) => node.tagName === "TD"));
  mounted.unmount();
});
