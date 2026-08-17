// The activation-module copy deck: every string the module stack renders,
// kept beside the renderer so chrome and copy review together.
// Module/submodule KEYS are engine vocabulary (stable ids in
// overview.activation.get responses); the strings here are the product
// copy for those keys. Which signal derives a module's state, and why the
// bonus targets are not blockers, are explanations of the model rather
// than anything a member acts on: they belong to the design record, never
// to this screen.

export const MODULE_TITLES = {
  finish_installation_wizard: "Finish the installation wizard",
  connect_harness: "Connect a harness",
  run_onboard: "Run /yoke onboard",
  first_deploy: "First deploy",
};

export const STATE_PILL_TEXT = {
  not_started: "waits",
  in_progress: "next up",
  activated: "activated",
};

// Wizard checklist rows, the first adapting to how the universe is hosted.
// Tail rows are recommended, never required.
export const WIZARD_MACHINE_ROWS = {
  hosted: "Machine connected",
  local: "Local universe created",
  "self-host": "Team server connected",
};
export const WIZARD_ROWS = {
  github: "GitHub connected",
  first_project: "First project created",
  hosting: "Hosting connected",
};
export const WIZARD_TAIL_KEYS = new Set(["github", "hosting"]);

export const RUN_ONBOARD_TITLE_HINT =
  "Run this in your harness — the web never invokes a skill";
export const DISMISS_HINT =
  "Dismiss — signals keep tracking; restore any time";
export const INSTALL_COMMAND = "curl -fsSL https://upyoke.com/install | sh";

// A harness whose sessions carry no hook-written telemetry is registered but
// not actually running Yoke's hooks. The engine names the harness's own trust
// surface; this is the sentence that wraps it.
export const hookTrustRemediation = (trustSurface) =>
  `Waiting on you — trust this project's hooks in ${trustSurface}.`;

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
