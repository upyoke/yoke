const commonMethod = {
  description: "A registered QA method.",
  success_policy_id: "all-pass",
  success_policy_params: {},
  used_by_plan_count: 0,
  plans: [],
};

const machineContext = {
  state: "in_use",
  concurrency_mode: "serial",
  wait_reason: "serial_lease_in_use",
  active_lease: { item_ref: "YOK-2001" },
};

const noCapabilities = {
  required_capability_kinds: [],
  required_capabilities: [],
};

const browserCapabilities = {
  required_capability_kinds: ["browser-control"],
  required_capabilities: [{
    kind: "browser-control",
    label: "Browser control",
    state: "ready",
    context: { state: "ready" },
  }],
};

const machineCapabilities = {
  required_capability_kinds: ["test-machine"],
  required_capabilities: [{
    kind: "test-machine",
    label: "Test Mac",
    state: "in_use",
    context: machineContext,
  }],
};

const missionCapabilities = {
  required_capability_kinds: ["browser-control", "test-machine"],
  required_capabilities: [
    {
      kind: "browser-control",
      label: "Browser control",
      state: "ready",
      context: { state: "ready" },
    },
    {
      kind: "test-machine",
      label: "Test Mac",
      state: "in_use",
      context: machineContext,
    },
  ],
};

export const methods = [
  {
    ...commonMethod,
    id: "command",
    name: "Command",
    source_kind: "built_in",
    source_ref: null,
    runner_id: "worktree_run",
    runner_gloss: "runs the case's command in the item worktree",
    ...noCapabilities,
    verdict_path: "automatic",
    verdict_contract: "exit 0 = pass",
    evidence_contract: "exit code · captured output tail",
    concurrency_mode: "parallel",
  },
  {
    ...commonMethod,
    id: "browser-check",
    name: "Browser check",
    source_kind: "built_in",
    source_ref: null,
    runner_id: "browser_substrate",
    runner_gloss:
      "the machine-local browser daemon — recorded on every run today",
    ...browserCapabilities,
    verdict_path: "automatic",
    verdict_contract: "assertions",
    evidence_contract: "assertions · trace · logs",
    concurrency_mode: "parallel",
  },
  {
    ...commonMethod,
    id: "browser-inspection",
    name: "Browser inspection",
    source_kind: "built_in",
    source_ref: null,
    runner_id: "browser_substrate",
    runner_gloss:
      "the machine-local browser daemon — recorded on every run today",
    ...browserCapabilities,
    verdict_path: "agent",
    verdict_contract:
      "inspects the screenshot against the case's expected outcome",
    evidence_contract: "screenshots · inspection verdict",
    concurrency_mode: "parallel",
  },
  {
    ...commonMethod,
    id: "terminal-check",
    name: "Terminal check",
    source_kind: "pack",
    source_ref: "machine-qa",
    runner_id: "host_control",
    runner_gloss: "SSH + PTY on the capability-named machine",
    ...machineCapabilities,
    verdict_path: "automatic",
    verdict_contract: "transcript checkpoints met",
    evidence_contract: "step transcript · checkpoint expectations",
    concurrency_mode: "serial",
  },
  {
    ...commonMethod,
    id: "terminal-inspection",
    name: "Terminal inspection",
    source_kind: "pack",
    source_ref: "machine-qa",
    runner_id: "host_control",
    runner_gloss: "SSH + PTY on the capability-named machine",
    ...machineCapabilities,
    verdict_path: "agent",
    verdict_contract:
      "inspects Terminal captures against the case's expected outcome",
    evidence_contract:
      "paired text + Terminal screenshots · inspection verdict",
    concurrency_mode: "serial",
  },
  {
    ...commonMethod,
    id: "machine-state-check",
    name: "Machine state check",
    source_kind: "pack",
    source_ref: "machine-qa",
    runner_id: "host_control",
    runner_gloss: "shell assertions on the controlled host",
    ...machineCapabilities,
    verdict_path: "automatic",
    verdict_contract: "exit 0 on the host",
    evidence_contract: "assertion commands · outputs · secret scan",
    concurrency_mode: "serial",
  },
  {
    ...commonMethod,
    id: "exploratory-mission",
    name: "Exploratory mission",
    source_kind: "pack",
    source_ref: "machine-qa",
    runner_id: "agent_mission",
    runner_gloss: "Main-owned mission with an informed or target-naive walker",
    ...missionCapabilities,
    verdict_path: "agent",
    verdict_contract: "pass, fail, or undetermined with a written rationale",
    evidence_contract: "ranked findings plus deliberate proof artifacts",
    concurrency_mode: "serial",
  },
];
