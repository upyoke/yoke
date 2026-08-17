// Shared fixtures for the Overview activation-module tests: an engine-shaped
// activation payload builder, a client that answers every Overview read, and
// the mount helper. Rows mirror overview.activation.get responses so the
// stack renders exactly what the engine serves.

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { FakeDocument, settle } from "./universe_ui_dom_test_support.mjs";

export const MODULE_KEYS = [
  "finish_installation_wizard", "connect_harness", "run_onboard",
  "first_deploy",
];

export function wizardSubmodules(done = {}, machineDetail = null) {
  return [
    {
      key: "machine_universe", label_key: "machine_universe",
      done: Boolean(done.machine), detail: machineDetail,
    },
    { key: "github", label_key: "github", done: Boolean(done.github), detail: null },
    {
      key: "first_project", label_key: "first_project",
      done: Boolean(done.project), detail: null,
    },
    { key: "hosting", label_key: "hosting", done: Boolean(done.hosting), detail: null },
  ];
}

// `health` / `trustSurfaces` mirror the engine's hook-health sub-signal:
// null on both means the harness declares no approval gate to report.
export function harnessTargets(hits = {}, health = {}, trustSurfaces = {}) {
  return [
    ["claude-code", "Claude Code"], ["codex", "Codex"], ["cursor", "Cursor"],
    ["claude-cli", "Claude CLI"], ["codex-cli", "Codex CLI"],
    ["cursor-cli", "Cursor CLI"],
    ["claude-vscode", "Claude in VS Code"], ["cursor-desktop", "Cursor IDE"],
  ].map(([key, label]) => ({
    key,
    label,
    hit: Boolean(hits[key]),
    hook_health: health[key] || null,
    trust_surface: trustSurfaces[key] || null,
  }));
}

export function activationAnswer({
  states = {}, extras = {}, dismissed = [], dismissAvailable = false,
} = {}) {
  return {
    dismiss_available: dismissAvailable,
    modules: MODULE_KEYS.map((key) => ({
      key,
      state: states[key] || "not_started",
      activated_at:
        (states[key] || "not_started") === "activated" ? "2026-07-20T00:00:00Z" : null,
      dismissed: dismissed.includes(key),
      submodules: [],
      ...(key === "connect_harness"
        ? { targets: harnessTargets(), projects: [], connected: null } : {}),
      ...(key === "finish_installation_wizard"
        ? { submodules: wizardSubmodules(), fully_complete: false } : {}),
      ...(extras[key] || {}),
    })),
  };
}

// A one-project universe answering every read the Overview composes; the
// section reads default non-empty so the ghost rule stays out of the way
// unless a test overrides one to empty.
export function activationClient(activation, overrides = {}) {
  const requests = [];
  const answers = {
    "frontier.list": {
      ready_rows: [{
        item_id: "YOK-9", project: "yoke", next_step: "advance",
        run_command: "yoke advance YOK-9", why_ready: "no blockers",
      }],
      blocked_rows: [],
    },
    "sessions.list": { rows: [] },
    "strategy.doc.list": {
      docs: [{ slug: "MISSION", title: "why", updated_at: "today" }],
    },
    "deployment_runs.list": {
      rows: [{
        id: "run-1", project: "yoke", flow: "stage-flow",
        target_tier: "persistent", target_environment: "stage",
        status: "succeeded", created_at: "1h",
      }],
    },
    "events.query.run": { rows: [] },
    "doctor.last_run.get": { never_run: true },
    "overview.activation.get": activation,
    "overview.vitals.get": {
      state_counts: {
        active: 0, pipeline: 0, backlog: 0, blocked: 0, frozen: 0, done: 0,
      },
      momentum: [],
      days: 120,
    },
    "overview.module.dismiss": { dismissed: true },
    "overview.module.restore": { dismissed: false },
    ...overrides,
  };
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
      if (request.function in answers) {
        return {
          status: 200,
          envelope: { success: true, result: answers[request.function] },
        };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

export async function mountOverview(client, capabilities) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/overview?project=1";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, {
    client, ...(capabilities ? { capabilities } : {}),
  });
  await settle();
  return { root, mounted };
}
