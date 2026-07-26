// The activation-module copy deck: every drawn string the module stack
// renders, kept beside the renderer so chrome and copy review together.
// Module/submodule KEYS are engine vocabulary (stable ids in
// overview.activation.get responses); the strings here are the product
// copy for those keys, including the quiet fine-print signal lines.

export const MODULE_TITLES = {
  finish_installation_wizard: "Finish the installation wizard",
  connect_harness: "Connect a harness",
  run_onboard: "Run /yoke onboard",
  first_deploy: "First deploy",
};

// The quiet fine-print signal line under each module title.
export const MODULE_SIGNAL_LINES = {
  finish_installation_wizard:
    "submodule signals listed inline — the module activates on the " +
    "required pair (machine/universe + project) and reads fully complete " +
    "on all four",
  connect_harness: "signal · HarnessSessionStarted carrying the executor",
  run_onboard: "signal · onboarding checklist (run_id) progress",
  first_deploy: "signal · a successful deployment run",
};

export const STATE_PILL_TEXT = {
  not_started: "waits",
  in_progress: "next up",
  activated: "activated",
};

// Wizard checklist rows: label + quiet signal, the first row adapting to how
// the universe is hosted. Tail rows are recommended, never required.
export const WIZARD_MACHINE_ROWS = {
  hosted: ["Machine connected", "machine-auth approval"],
  local: [
    "Local universe created", 'yoke init --local / wizard "this machine"',
  ],
  "self-host": ["Team server connected", "server connect"],
};
export const WIZARD_ROWS = {
  github: ["GitHub connected", "GitHub App binding"],
  first_project: ["First project created", "projects.create"],
  hosting: ["Hosting connected", "aws-admin capability saved"],
};
export const WIZARD_TAIL_KEYS = new Set(["github", "hosting"]);

export const RUN_ONBOARD_TITLE_HINT =
  "Run this in your harness — the web never invokes a skill";
export const DISMISS_HINT =
  "Dismiss — signals keep tracking; restore any time";
export const TARGET_NOTE =
  "any one activates — the rest stay as bonus targets, never blockers";
export const INSTALL_COMMAND = "curl -fsSL https://upyoke.com/install | sh";

export const MODULE_COPY = {
  connect_harness: {
    in_progress: "Open a supported harness in a project directory:",
  },
  run_onboard: {
    in_progress:
      "In your harness: strategy → execution profile → Packs → envs → " +
      "domain → infra.",
    activated:
      "Execution-ready — strategy filled, webapp-scaffold installed, " +
      "stage + prod provisioned.",
  },
  first_deploy: {
    in_progress:
      "Approve the gated infra apply + first deploy in your harness — " +
      "pulumi up stays behind your explicit yes.",
    activated: "Live — onboarding is done.",
  },
};

// Day-zero ghost panels: hint line per section, keyed to the module whose
// activation retires the ghost.
export const GHOST_HINTS = {
  strategy: "Strategy · activates as the docs fill via /yoke onboard",
  frontier: "Frontier · activates when the first items are seeded",
  delivery: "Delivery · activates on the first deployment run",
};
export const GHOST_MODULES = {
  strategy: "run_onboard",
  frontier: "run_onboard",
  delivery: "first_deploy",
};
