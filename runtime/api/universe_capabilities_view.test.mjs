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
                  type: "test-machine", kind: "test_resource", state: "in_use",
                  project: "yoke", project_id: 1,
                  settings_summary: "mac-mini-lab · Terminal + PTY · baselines ×2",
                  used_by_summary: "Machine methods ×3",
                  verified_at: "2026-07-15T12:10:00Z",
                  verified_source: "capability",
                },
                {
                  type: "github", kind: "provider_access", state: "ready",
                  project: "yoke",
                  settings_summary: "example-org/example-repo",
                  used_by_summary: "GitHub · delivery",
                  verified_at: "2026-07-15T12:00:00Z",
                  verified_source: "repo-binding",
                },
                {
                  type: "migration_model", kind: "declared_model",
                  state: "ready", project: "yoke",
                  settings_summary: "primary (governed_module)",
                  used_by_summary: "all workflows",
                  verified_at: null, verified_source: null,
                },
                {
                  type: "aws-admin", kind: "provider_access",
                  state: "configured_unverified", project: "yoke",
                  settings_summary: "",
                  used_by_summary: "Delivery · Infrastructure",
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
    "test-machine", "test resource",
    "mac-mini-lab · Terminal + PTY · baselines ×2",
    "Machine methods ×3", "2026-07-15T12:10:00Z", "in use",
    "github", "provider access", "example-org/example-repo",
    "GitHub · delivery", "2026-07-15T12:00:00Z", "ready",
    "migration_model", "declared model", "primary (governed_module)",
    "all workflows", "never", "ready",
    "aws-admin", "provider access", "—", "Delivery · Infrastructure",
    "never", "configured (unverified)",
  ]);
  // Kind and state color through the semantic pill families. The engine
  // derives both values; configured-but-never-verified reads as loudly as
  // broken (warn), never as neutral idle.
  const pills = allNodes(root)
    .filter((node) => node.classList && node.classList.contains("pill"));
  assert.deepEqual(
    pills.map((pill) => pill.className),
    [
      "pill good", "pill run",
      "pill run", "pill good",
      "pill idle", "pill good",
      "pill run", "pill warn",
    ],
  );
  // The capability column is the stored identifier, dressed as code.
  const monoCells = allNodes(root)
    .filter((node) => node.tagName === "TD" &&
      node.classList && node.classList.contains("mono"))
    .map(cellText);
  assert.deepEqual(
    monoCells,
    ["test-machine", "github", "migration_model", "aws-admin"],
  );
  const machineLink = allNodes(root).find(
    (node) => node.classList?.contains("row-link"),
  );
  assert.equal(machineLink.href, "#/capabilities/test-machine?project=1");
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
  assert.ok(text.includes("No capabilities in this scope."));
  mounted.unmount();
});
