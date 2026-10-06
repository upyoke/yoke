// The Runs table on Deployments: the run ID is the link, the flow name is
// plain text, the status cell stays a table cell, the evidence cell holds a
// few small thumbnails with "and N more" beneath, and the table stacks
// whenever its content pane cannot hold every column.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { renderRunsTable } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_delivery_runs_table.js";
import { FakeDocument, allNodes, byClass } from "./universe_ui_dom_test_support.mjs";

const STATIC = new URL("../../packages/yoke-core/src/yoke_core/ui/static/", import.meta.url);

function artifact(id) {
  return {
    id, artifact_type: "command-output", content_type: "text/plain",
    label: `output ${id}`, qa_requirement_id: 9,
  };
}

function renderTable(artifactCount, navigations = []) {
  const documentNode = new FakeDocument();
  const body = documentNode.createElement("div");
  const context = {
    document: documentNode,
    projects: () => [{ id: 1, slug: "alpha", name: "Alpha" }],
    capabilities: {},
    client: { call: async () => ({ status: 200, envelope: { success: true, result: {} } }) },
    navigate: (href) => navigations.push(href),
  };
  const row = {
    id: "run-20260927-001", flow: "alpha-release", project: "alpha",
    status: "succeeded", target_environment: "prod", stages: [],
    created_at: "2026-09-27T10:00:00Z",
  };
  const artifacts = Array.from({ length: artifactCount }, (_, index) => artifact(index + 1));
  const facts = {
    evidence: new Map([[row.id, { checks: [], artifacts }]]),
    flowNames: new Map(),
    failed: null,
  };
  renderRunsTable(context, body, [row], {
    facts, flowLabels: new Map([["alpha-release", "Alpha Release"]]), scope: "1", reload: () => {},
  });
  return body;
}

test("the run ID links to the run and the flow name is plain text", () => {
  const body = renderTable(0);
  const title = byClass(body, "delivery-run-title")[0];
  assert.equal(title.tagName, "DIV");
  assert.equal(title.textContent, "Alpha Release");
  const runId = byClass(body, "delivery-run-id")[0];
  assert.equal(runId.tagName, "A");
  assert.equal(runId.textContent, "run-20260927-001");
  assert.equal(runId.href, "/deployments/runs/run-20260927-001?project=1");
  // One link per row: nothing else in the release cell navigates.
  const releaseCell = allNodes(body).find((node) => node.tagName === "TD");
  assert.equal(allNodes(releaseCell).filter((node) => node.tagName === "A").length, 1);
});

test("carried items are chips the link underline skips", () => {
  const documentNode = new FakeDocument();
  const body = documentNode.createElement("div");
  renderRunsTable({
    document: documentNode, projects: () => [{ id: 1, slug: "alpha" }], capabilities: {},
    client: { call: async () => ({}) }, navigate: () => {},
  }, body, [{
    id: "run-1", flow: "f", project: "alpha", status: "succeeded", stages: [],
    member_items: [
      { public_ref: "YOK-5", project_id: 1, project_sequence: 5, ref: "YOK-5" },
      { public_ref: "YOK-6", ref: "YOK-6" },
    ],
  }], { facts: { evidence: new Map(), flowNames: new Map() }, flowLabels: new Map(), scope: "1" });
  // Linked and unlinked carried items read the same.
  const chips = byClass(body, "delivery-member");
  assert.deepEqual(chips.map((chip) => chip.tagName), ["A", "SPAN"]);
  for (const chip of chips) {
    assert.match(chip.className, /chip/);
  }
  const css = readFileSync(new URL("universe_link_underline.css", STATIC), "utf8");
  assert.match(css, /:not\(\[class\*="chip"\]\)/);
});

test("the status cell is a plain table cell holding the pill", () => {
  const body = renderTable(0);
  const cell = byClass(body, "delivery-run-status-cell")[0];
  assert.equal(cell.tagName, "TD");
  assert.equal(cell.classList.contains("delivery-run-status"), false);
  assert.equal(byClass(cell, "pill")[0].textContent, "succeeded");
});

test("the evidence cell shows three items and says how many more", () => {
  const body = renderTable(5);
  const cell = byClass(body, "delivery-run-evidence-cell")[0];
  assert.equal(byClass(cell, "review-more").length, 0);
  assert.equal(byClass(cell, "delivery-run-evidence-more")[0].textContent, "and 2 more");
  const few = renderTable(2);
  assert.equal(byClass(few, "delivery-run-evidence-more").length, 0);
  const none = renderTable(0);
  assert.equal(byClass(none, "delivery-run-evidence-cell")[0].textContent, "—");
});

test("runs table CSS keeps thumbnails small and the status cell a table cell", () => {
  const css = readFileSync(new URL("universe_run_rosters.css", STATIC), "utf8");
  assert.doesNotMatch(css, /delivery-run-evidence-cell\s*\{[^}]*min-width/);
  assert.match(css, /delivery-run-evidence-cell \.review-evidence\.compact \.review-shot \{\s*width: 44px;/);
  assert.doesNotMatch(css, /delivery-run-status-cell\s*\{[^}]*display:\s*flex/);
  // Must outweigh the shared `table.items td:has(.pill)` top alignment.
  assert.match(
    css,
    /\.universe-app-root table\.items\.delivery-runs-table td\.delivery-run-status-cell \{\s*vertical-align: middle;/,
  );
});

test("stacking tables switch on their content pane at 840px", () => {
  const css = readFileSync(new URL("table_stacks_narrow.css", STATIC), "utf8");
  assert.match(css, /@container dashboard-content \(max-width: 840px\)/);
  assert.doesNotMatch(css, /@media \(max-width: 720px\)/);
});

test("clicking a run row does not navigate; only the run ID does", () => {
  const navigations = [];
  const body = renderTable(0, navigations);
  byClass(body, "delivery-run-row")[0].dispatchEvent(new Event("click"));
  assert.deepEqual(navigations, []);
  assert.doesNotMatch(readFileSync(new URL("universe_run_rosters.css", STATIC), "utf8"),
    /delivery-run-row/);
});

test("table evidence tiles draw their loading state without words", () => {
  const css = readFileSync(new URL("universe_run_rosters.css", STATIC), "utf8");
  const rule = css.match(
    /\.delivery-run-evidence-cell \.review-shot-state,\s*\.universe-app-root \.qa-activity-evidence \.review-shot-state \{([^}]*)\}/,
  );
  assert.ok(rule, "compact table tiles need their own state rule");
  assert.match(rule[1], /font-size:\s*0/);
  assert.match(rule[1], /overflow:\s*hidden/);
});
