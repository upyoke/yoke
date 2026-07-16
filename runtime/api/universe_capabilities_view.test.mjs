import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

test("Capabilities shows stored types with derived kind, state, and freshness", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/capabilities?project=1";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, name: "Yoke" }] } } };
      }
      if (request.function === "projects.capabilities.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [
                {
                  type: "github", kind: "provider_access", state: "verified",
                  project: "yoke",
                  settings_summary: "example-org/example-repo",
                  verified_at: "2026-07-15T12:00:00Z",
                  verified_source: "repo-binding",
                },
                {
                  type: "migration_model", kind: "declared_model",
                  state: "declared", project: "yoke",
                  settings_summary: "primary (governed_module)",
                  verified_at: null, verified_source: null,
                },
                {
                  type: "aws-admin", kind: "provider_access",
                  state: "configured_unverified", project: "yoke",
                  settings_summary: "",
                  verified_at: null, verified_source: null,
                },
              ],
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  assert.deepEqual(
    requests.find((request) => request.function === "projects.capabilities.list"),
    { function: "projects.capabilities.list", payload: { project: "1" } },
  );
  // The stored type vocabulary renders verbatim; an unverified stamp reads
  // "never" and an empty settings summary reads as an em-dash.
  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells, [
    "github", "provider_access", "example-org/example-repo",
    "2026-07-15T12:00:00Z", "verified",
    "migration_model", "declared_model", "primary (governed_module)",
    "never", "declared",
    "aws-admin", "provider_access", "—", "never", "configured_unverified",
  ]);
  // Kind and state color through the semantic pill families. The engine
  // derives both values; configured-but-never-verified reads as loudly as
  // broken (warn), never as neutral idle.
  const pills = allNodes(root)
    .filter((node) => node.classList && node.classList.contains("pill"));
  assert.deepEqual(
    pills.map((pill) => pill.className),
    [
      "pill run", "pill good",
      "pill idle", "pill idle",
      "pill run", "pill warn",
    ],
  );
  // The capability column is the stored identifier, dressed as code.
  const monoCells = allNodes(root)
    .filter((node) => node.tagName === "TD" &&
      node.classList && node.classList.contains("mono"))
    .map(cellText);
  assert.deepEqual(monoCells, ["github", "migration_model", "aws-admin"]);
  mounted.unmount();
});

test("Capabilities renders its honest empty state", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/capabilities";
  const root = documentNode.createElement("div");
  const requests = [];
  const client = {
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [{ id: 1, name: "Yoke" }] } } };
      }
      if (request.function === "projects.capabilities.list") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  // The "all" default reads unfiltered: no project key in the payload.
  assert.deepEqual(
    requests.find((request) => request.function === "projects.capabilities.list"),
    { function: "projects.capabilities.list", payload: {} },
  );
  const text = allNodes(root)
    .map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes("no capabilities declared yet"));
  mounted.unmount();
});
