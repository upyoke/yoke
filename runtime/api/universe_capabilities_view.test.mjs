import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  relativeAge,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_time.js";
import {
  FakeDocument,
  allNodes,
  cellText,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function keyEvent(key) {
  const event = new Event("keydown", { cancelable: true });
  Object.defineProperty(event, "key", { value: key });
  return event;
}

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
                  display_type: "test-mac", display_label: "Test Lab",
                  display_order: 0, detail_view: "test-machine",
                  active_item_ref: "YOK-2001",
                  project: "yoke", project_id: 1,
                  settings_summary: "mac-mini-lab · Terminal + PTY · baselines ×2",
                  used_by_summary: "Machine methods ×3",
                  verified_at: "2026-07-15T12:10:00Z",
                  verified_source: "capability",
                },
                {
                  type: "github", kind: "provider_access", state: "ready",
                  display_label: "GitHub", display_order: 40, detail_view: "",
                  project: "yoke",
                  settings_summary: "example-org/example-repo",
                  used_by_summary: "GitHub · delivery",
                  verified_at: "2026-07-15T12:00:00Z",
                  verified_source: "repo-binding",
                },
                {
                  type: "migration_model", kind: "declared_model",
                  display_label: "Migration model", display_order: 30,
                  state: "ready", project: "yoke",
                  settings_summary: "primary (governed_module)",
                  used_by_summary: "all workflows",
                  verified_at: null, verified_source: null,
                },
                {
                  type: "aws-admin", kind: "provider_access",
                  display_label: "AWS admin", display_order: 50,
                  state: "configured_unverified", project: "yoke",
                  settings_summary: "",
                  used_by_summary: "Delivery · Environments",
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

  assert.match(
    allNodes(root).map((node) => node.textContent || "").join(" "),
    /A baseline is a registered operation on the capability's executor — reached and verified by code, never instructions a reader is trusted to follow\./,
  );
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
    "Test Lab", "yoke", "test resource",
    "mac-mini-lab · Terminal + PTY · baselines ×2",
    "Machine methods ×3", relativeAge("2026-07-15T12:10:00Z"),
    "in use · YOK-2001",
    "Migration model", "yoke", "declared model", "primary (governed_module)",
    "all workflows", "never", "ready",
    "GitHub", "yoke", "provider access", "example-org/example-repo",
    "GitHub · delivery", relativeAge("2026-07-15T12:00:00Z"), "ready",
    "AWS admin", "yoke", "provider access", "—", "Delivery · Environments",
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
      "pill idle", "pill good",
      "pill run", "pill good",
      "pill run", "pill warn",
    ],
  );
  // The list keeps the stored identifier in its payload while rendering the
  // prototype's compact display slug for the composite Test Mac resource.
  const monoCells = allNodes(root)
    .filter((node) => node.tagName === "TD" &&
      node.classList && node.classList.contains("mono"))
    .map(cellText);
  assert.deepEqual(
    monoCells,
    ["Test Lab", "Migration model", "GitHub", "AWS admin"],
  );
  const machineLink = allNodes(root).find(
    (node) => node.classList?.contains("row-link"),
  );
  assert.equal(machineLink.href, "#/capabilities/test-machine?project=1");
  const machineRow = machineLink.parentNode.parentNode;
  assert.equal(machineRow.tagName, "TR");
  assert.equal(machineRow.attributes.get("role"), "link");
  assert.equal(machineRow.attributes.get("tabindex"), "0");
  assert.equal(
    machineRow.attributes.get("aria-label"),
    "Open Test Lab capability",
  );
  machineRow.dispatchEvent(new Event("click"));
  assert.equal(
    documentNode.defaultView.location.hash,
    "#/capabilities/test-machine?project=1",
  );
  documentNode.defaultView.location.hash = "#/capabilities?project=1";
  const enter = keyEvent("Enter");
  machineRow.dispatchEvent(enter);
  assert.equal(enter.defaultPrevented, true);
  assert.equal(
    documentNode.defaultView.location.hash,
    "#/capabilities/test-machine?project=1",
  );
  documentNode.defaultView.location.hash = "#/capabilities?project=1";
  const space = keyEvent(" ");
  machineRow.dispatchEvent(space);
  assert.equal(space.defaultPrevented, true);
  assert.equal(
    documentNode.defaultView.location.hash,
    "#/capabilities/test-machine?project=1",
  );
  assert.deepEqual(
    allNodes(root)
      .filter((node) => node.tagName === "TIME")
      .map((node) => node.attributes.get("datetime")),
    ["2026-07-15T12:10:00.000Z", "2026-07-15T12:00:00.000Z"],
  );
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
  assert.deepEqual(
    allNodes(root)
      .filter((node) => node.tagName === "TH")
      .map((node) => node.textContent),
    [
      "capability", "project", "kind", "settings",
      "used by", "verified", "state",
    ],
  );
  const emptyCell = allNodes(root).find(
    (node) => node.tagName === "TD" && node.textContent ===
      "No capabilities in this scope.",
  );
  assert.equal(emptyCell.attributes.get("colspan"), "7");
  mounted.unmount();
});

test("Capabilities all-project table renders the served project emoji", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/capabilities";
  const root = documentNode.createElement("div");
  const client = {
    async call(request) {
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Yoke" } } };
      }
      if (request.function === "projects.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [{
                id: 1, slug: "yoke", name: "Yoke", emoji: "🐄",
              }],
            },
          },
        };
      }
      if (request.function === "projects.capabilities.list") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              rows: [{
                type: "github",
                kind: "provider_access",
                state: "ready",
                project: "yoke",
                project_id: 1,
                settings_summary: "upyoke/yoke",
                used_by_summary: "GitHub · delivery",
                verified_at: null,
              }],
            },
          },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };

  const mounted = mountUniverseApp(root, { client });
  await settle();

  const cells = allNodes(root)
    .filter((node) => node.tagName === "TD")
    .map(cellText);
  assert.deepEqual(cells.slice(0, 2), ["github", "🐄 yoke"]);
  mounted.unmount();
});
