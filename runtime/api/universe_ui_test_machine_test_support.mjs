import {
  FakeDocument,
  allNodes,
} from "./universe_ui_dom_test_support.mjs";

export const detail = {
  project_id: 1,
  project: "yoke",
  kind: "test-machine",
  machine: "mac-mini-lab",
  capability_type: "test-machine:mac-mini-lab",
  display_name: "Test Mac",
  runner_id: "host_control",
  settings: {
    resource_name: "mac-mini-lab",
    host: "test-mac.local",
    user: "yoke-test",
    host_kind: "mac-ssh",
    operating_notes:
      "Do not interrupt an active lease; keep Terminal region unobscured.",
  },
  settings_token: "{\"host\":\"test-mac.local\"}",
  features: ["Terminal.app", "PTY", "screenshots", "post-install shell"],
  host_baselines: ["fresh-host", "shell-preconfigured"],
  host_baseline_end_states: {
    "fresh-host": "the host carries its captured user state and no Yoke at all",
    "shell-preconfigured":
      "the host carries its captured user state plus the current Yoke launcher on both shell surfaces; it is NOT a fresh host",
  },
  host_kinds: ["mac-ssh"],
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
    host_end_state:
      "the host carries its captured user state plus the current Yoke launcher on both shell surfaces; it is NOT a fresh host",
  },
  operations: [
    {
      operation: "reset",
      status: "verified",
      performed_at: "2026-07-26T17:00:00Z",
      error_code: null,
      checks: [{ name: "fresh-host", ok: true }],
    },
  ],
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
    item: {
      id: 2001,
      ref: "YOK-2001",
      title: "Prove the installer campaign",
    },
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

export function context(machines = [detail]) {
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
          if (request.function === "test_machine.list") {
            return {
              status: 200,
              envelope: { success: true, result: { machines } },
            };
          }
          if (request.function === "test_machine.get") {
            const selected = machines.find(
              (machine) => machine.machine === request.payload.machine,
            );
            return {
              status: 200,
              envelope: { success: true, result: selected || detail },
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

export function text(root) {
  return allNodes(root).map((node) => node.textContent).join(" ");
}
