import assert from "node:assert/strict";
import test from "node:test";

import {
  renderMachineDetail,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machine_detail.js";
import {
  FakeDocument, byClass, settle, visibleText,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

function detailResult(overrides = {}) {
  return {
    machine: {
      machine_id: "11111111-1111-4111-8111-111111111111",
      name: "Studio",
      owner: "Avery",
      registered_at: "2026-09-01T12:00:00Z",
      access: {
        use: {
          mode: "actors", actor_ids: [7], project_id: null, role: "",
        },
      },
    },
    relay: {
      liveness: "connected",
      relay_version: "0.1.1",
      last_seen_at: "2026-09-08T12:00:00Z",
      plan_limits: { "codex-cli": { plan_tier: "Team" } },
    },
    token: {
      status: "active",
      created_at: "2026-09-01T12:00:00Z",
      last_used_at: "2026-09-08T11:59:00Z",
    },
    credential_presence: {
      github: true,
      aws: false,
      harnesses: { "codex-cli": true },
    },
    harnesses: [
      { key: "codex", label: "Codex", status: "active", version: "1.0" },
      {
        key: "codex-cli", label: "Codex CLI", status: "active", version: "1.0",
      },
    ],
    projects: [{
      slug: "yoke",
      name: "Yoke",
      checkout: "/work/yoke",
      recovery: "Run /yoke onboard in this project checkout.",
      hook_reports: [{
        harness_id: "codex",
        approval_state: "unapproved",
        trust_surface: "Codex's hook-trust prompt",
      }],
    }],
    surface_policies: [],
    running_sessions: [{ surface: "codex-cli", mode: "working" }],
    recent_launches: [{
      selected_surface: "codex-cli", state: "failed", created_at: "now",
    }],
    ...overrides,
  };
}

async function render(result) {
  const documentNode = new FakeDocument();
  const requests = [];
  const context = {
    document: documentNode,
    isMounted: () => true,
    client: {
      async call(request) {
        requests.push(request);
        return ok(result);
      },
    },
  };
  const main = documentNode.createElement("main");
  renderMachineDetail(context, main, null, result.machine.machine_id);
  await settle();
  return { main, requests };
}

test("machine detail composes identity, credential, hook, and history facts", async () => {
  const { main, requests } = await render(detailResult());
  const copy = visibleText(main, " ");

  assert.equal(requests[0].function, "machine.detail");
  assert.match(copy, /Studio/);
  assert.match(copy, /Avery/);
  assert.match(copy, /Token last used/);
  assert.match(copy, /GitHub present/);
  assert.match(copy, /AWS not reported/);
  assert.match(copy, /Team/);
  assert.match(copy, /\/work\/yoke/);
  assert.match(copy, /trust this project's hooks in Codex's hook-trust prompt/);
  assert.match(copy, /Run \/yoke onboard/);
  assert.match(copy, /Running now/);
  assert.match(copy, /Recent starts/);
  assert.equal(byClass(main, "machine-harness-row").length, 2);
  assert.equal(byClass(main, "machine-harness-row")[0].children.length, 1);
  assert.equal(byClass(main, "machine-harness-row")[1].children.length, 2);
});

test("a retired machine remains readable but has no active controls", async () => {
  const result = detailResult();
  result.machine.retired_at = "2026-09-08T12:00:00Z";
  const { main } = await render(result);

  assert.match(visibleText(main, " "), /Retired/);
  assert.equal(byClass(main, "machine-retire").length, 0);
  assert.ok(byClass(main, "machine-access-select")[0].disabled);
  assert.ok(byClass(main, "machine-harness-row")[1].children[1].disabled);
});
