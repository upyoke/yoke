import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

const PROJECTS = [{ id: 1, slug: "demo", name: "Demo" }];

function architectureClient(health, calls) {
  return {
    call(request) {
      calls.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: PROJECTS });
      }
      if (request.function === "project_structure.architecture_health.get") {
        return okEnvelope({ project_id: "demo", health });
      }
      return okEnvelope({});
    },
  };
}

async function mountAt(t, hash, client) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  mountUniverseApp(root, { client });
  await settle();
  return root;
}

function pageText(root) {
  return allNodes(root).map((node) => node.textContent || "").join("\n");
}

test("an undeclared map explains itself and names the draft recipe", async (t) => {
  const calls = [];
  const root = await mountAt(
    t, "#/architecture/demo", architectureClient({ declared: false }, calls),
  );
  const text = pageText(root);
  assert.match(text, /declares no architecture map yet/);
  assert.match(text, /architecture-draft get --project/);
  assert.ok(calls.some(
    (request) =>
      request.function === "project_structure.architecture_health.get",
  ));
});

test("health renders above the declared map from one read", async (t) => {
  const calls = [];
  const health = {
    declared: true,
    python_paths: 4,
    classified: 2,
    exempt: 1,
    unclassified: 1,
    coverage_pct: 75.0,
    forbidden_edge_count: 1,
    cross_cutting_count: 0,
    forbidden_edge_examples: [{
      path: "src/api.py",
      source_layer: "storage",
      imported_layer: "service",
      imported_module: "src.store",
    }],
    cross_cutting_examples: [],
    layers: [
      { id: "storage", may_depend_on: [], forbidden_edges: [] },
      { id: "service", may_depend_on: ["storage"], forbidden_edges: [] },
    ],
    domains: [{ id: "billing", pattern_count: 2 }],
    entrypoints: ["storage_access"],
    exemption_patterns: 1,
  };
  const root = await mountAt(
    t, "#/architecture/demo", architectureClient(health, calls),
  );
  const text = pageText(root);
  assert.match(text, /75% of 4 python files/);
  assert.match(text, /storage → service via src\.store/);
  assert.match(text, /may depend on storage/);
  assert.match(text, /billing/);
  assert.match(text, /storage_access/);
  const healthCalls = calls.filter(
    (request) =>
      request.function === "project_structure.architecture_health.get",
  );
  assert.equal(healthCalls.length, 1);
});
