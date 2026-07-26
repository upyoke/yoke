import assert from "node:assert/strict";
import test from "node:test";

import { renderTestMachineDetail } from
  "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_test_machine.js";
import { machineRelativeAge } from
  "../../packages/yoke-core/src/yoke_core/ui/static/test_machine_view_primitives.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

const detail = {
  project_id: 1,
  project: "yoke",
  kind: "test-machine",
  display_name: "Test Mac",
  executor_id: "host_control",
  settings: {
    resource_name: "mac-mini-lab",
    host: "test-mac.local",
    user: "yoke-test",
    operating_notes: "Do not interrupt an active lease.",
  },
  settings_token: "{\"host\":\"test-mac.local\"}",
  features: ["Terminal.app", "PTY", "screenshots", "post-install shell"],
  host_baselines: ["fresh-host", "shell-preconfigured"],
  concurrency: { limit: 1, mode: "serial" },
  verification: {
    status: "verified",
    checked_at: "2026-07-26T16:00:00Z",
    error_code: null,
    checks: [
      { name: "connection", ok: true },
      { name: "terminal_bridge", ok: true },
      {
        name: "fresh-host",
        ok: true,
        verified_property: "tool directory membership in shell PATH",
      },
      {
        name: "shell-preconfigured",
        ok: true,
        verified_property: "tool directory absence from shell PATH",
      },
    ],
  },
  secrets: [
    { key: "screen_control_token", stored: false },
    { key: "ssh_private_key", stored: true },
    { key: "sudo_password", stored: true },
  ],
  active_lease: {
    id: 9,
    session_id: "session-machine",
    actor_id: "2",
    acquired_at: "2026-07-26T15:58:00Z",
    heartbeat_at: "2026-07-26T15:59:00Z",
  },
  methods: [
    { id: "terminal-check", name: "Terminal check", source_ref: "machine-qa" },
    {
      id: "terminal-inspection",
      name: "Terminal inspection",
      source_ref: "machine-qa",
    },
    {
      id: "machine-state-check",
      name: "Machine state check",
      source_ref: "machine-qa",
    },
  ],
};

function context() {
  const requests = [];
  const documentNode = new FakeDocument();
  return {
    requests,
    documentNode,
    value: {
      document: documentNode,
      isMounted: () => true,
      client: {
        async call(request) {
          requests.push(request);
          if (request.function === "test_machine.get") {
            return {
              status: 200,
              envelope: { success: true, result: detail },
            };
          }
          if (request.function === "test_machine.settings_replace") {
            return {
              status: 200,
              envelope: { success: true, result: { project: "yoke" } },
            };
          }
          if (request.function === "test_machine.verify") {
            return {
              status: 200,
              envelope: { success: true, result: { status: "verified" } },
            };
          }
          throw new Error(`unexpected function ${request.function}`);
        },
      },
    },
  };
}

function text(root) {
  return allNodes(root).map((node) => node.textContent).join(" ");
}

test("machine timestamps use compact prototype-relative labels", () => {
  const now = Date.parse("2026-07-26T16:11:00Z");
  assert.equal(machineRelativeAge("2026-07-26T16:00:00Z", now), "11m");
  assert.equal(machineRelativeAge("2026-07-26T15:00:00Z", now), "1h");
  assert.equal(machineRelativeAge("2026-07-24T15:00:00Z", now), "2d");
  assert.equal(machineRelativeAge(null, now), "recently");
});

test("Test Mac detail matches capability, lease, method, and receipt prototype", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");

  const rendered = text(main);
  assert.match(rendered, /test-machine capability · composite · yoke/);
  assert.match(rendered, /Terminal\.app · PTY · screenshots · post-install shell/);
  assert.match(rendered, /fresh-host · shell-preconfigured/);
  assert.match(
    rendered,
    /run inside the lease; each verifies the branch-determining state it promises/,
  );
  assert.match(rendered, /1 · serial/);
  assert.match(rendered, /3 \/ 3 checks/);
  assert.match(rendered, /session-machine/);
  assert.match(rendered, /Terminal check/);
  assert.match(rendered, /Terminal inspection/);
  assert.match(rendered, /Machine state check/);
  assert.match(rendered, /Credential references/);
  assert.doesNotMatch(rendered, /top-secret/);
  assert.equal(byClass(main, "test-machine-check").length, 3);
  assert.match(rendered, /SSH \+ executor materialization/);
  assert.match(rendered, /sample artifact discarded after verification/);
  assert.match(rendered, /Host baselines reached \+ verified/);
  assert.match(
    rendered,
    /asserted the branch-determining state itself, never a proxy/,
  );
});

test("settings modal keeps secrets terminal-only and invalidates through typed write", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  const edit = allNodes(main).find((node) => node.textContent === "Edit settings");
  edit.dispatchEvent(new Event("click"));

  assert.equal(byClass(main, "test-machine-dialog").length, 1);
  const dialog = byClass(main, "test-machine-dialog")[0];
  assert.equal(dialog.attributes.get("aria-label"), "Edit Test Mac settings");
  const rendered = text(main);
  assert.match(rendered, /Secret values never enter the browser/);
  assert.match(
    rendered,
    /replacement happens through the registered terminal surface with --value-stdin/,
  );
  assert.match(
    rendered,
    /capability secret set --project yoke --cap-type test-machine/,
  );
  assert.match(rendered, /executor subprocess only/);
  assert.match(rendered, /used only by registered host-baseline operations/);
  assert.match(rendered, /Terminal automation bridge/);
  assert.match(rendered, /stored/);
  assert.match(rendered, /missing/);
  assert.match(rendered, /registered executor operations/);

  const save = allNodes(main).find(
    (node) => node.textContent === "Save non-secret settings",
  );
  save.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(
    prepared.requests.some(
      (request) => request.function === "test_machine.settings_replace",
    ),
    true,
  );
});

test("settings modal closes from its overlay", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  const edit = allNodes(main).find((node) => node.textContent === "Edit settings");
  edit.dispatchEvent(new Event("click"));

  const overlay = byClass(main, "test-machine-overlay")[0];
  overlay.dispatchEvent(new Event("click"));
  assert.equal(byClass(main, "test-machine-dialog").length, 0);
});

test("Verify now calls the registered verifier, never a browser-side recipe", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  const verify = allNodes(main).find((node) => node.textContent === "Verify now");
  verify.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(
    prepared.requests.some(
      (request) => request.function === "test_machine.verify",
    ),
    true,
  );
});
