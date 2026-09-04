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
  first_deploy: {
    in_progress:
      "Approve the gated infra apply + first deploy in your harness — " +
      "pulumi up stays behind your explicit yes.",
    activated: "Live — onboarding is done.",
  },
};

// Machine rows. Every registered machine answers the harness module for
// itself, so the copy names the machine before it names the harness. A
// machine the control plane knows only by id has no hostname yet, and its
// id renders whole: machine ids collide at any prefix.
export const machineNameOf = (machine) =>
  machine.name || `machine ${String(machine.machine_id || "")}`;
export const machineNamesLine = (machines) => {
  const names = machines.map(machineNameOf);
  return machines.length === 1
    ? `· ${names[0]}`
    : `· ${machines.length} machines: ${names.join(", ")}`;
};
export const machineMetaLine = (surfaces, lastSeen) => {
  const parts = [];
  if (surfaces && surfaces.length) parts.push(surfaces.join(", "));
  if (lastSeen !== null && lastSeen !== undefined) {
    parts.push(`seen ${lastSeen} ago`);
  }
  return parts.length ? `· ${parts.join(" · ")}` : "";
};
export const machineConnectedLine = (executor, relative) => (
  relative === null
    ? `${executor} connected.`
    : `${executor} connected ${relative} ago.`
);
export const MACHINE_PENDING_COPY =
  "Next up — open a supported harness on this machine.";

// The /yoke onboard module speaks from its own checklist run, so its copy
// is a set of sentence builders rather than one line per state. Before a
// run exists there is nothing to report but the route; once one exists,
// every line below names something that run actually did.
export const ONBOARD_NO_RUN =
  "In your harness: strategy → execution profile → Packs → envs → " +
  "domain → infra.";
export const onboardBlockedLine = (step, title, detail) =>
  `Blocked at ${step} ${title}${detail ? ` — ${detail}` : ""}.`;
export const onboardNextLine = (step, title) => `Next: ${step} ${title}.`;
export const onboardStepsLine = (done, total) =>
  `${done} of ${total} steps done.`;

// A finished run claims only the outcomes the universe can show. A mapped
// existing app finishes with no scaffold installed, and a run may finish
// having deferred its environments, so each clause is earned separately.
export const ONBOARD_OUTCOMES = {
  strategy: "strategy filled",
  scaffold: "webapp-scaffold installed",
};
export const onboardEnvironmentsOutcome = (names) =>
  `${names.join(" + ")} provisioned`;
export const onboardCompleteLine = (outcomes) => (
  outcomes.length
    ? `Execution-ready — ${outcomes.join(", ")}.`
    : "Onboarding checklist complete."
);
// A project that deployed is past onboarding whatever its checklist says;
// the engine closed the run and named the deployment that overtook it.
export const onboardSupersededLine = (deploymentRunId, at) =>
  `Onboarding done — superseded by deployment ${deploymentRunId}` +
  `${at ? ` on ${String(at).slice(0, 10)}` : ""}.`;
