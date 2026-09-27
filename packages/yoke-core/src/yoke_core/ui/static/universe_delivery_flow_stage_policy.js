// What a release stage does, in plain words: what runs it, the scope it
// operates at, where it acts, and — for a QA or approval stage — who decides.
//
// Every run freezes the definition it references, so these are the terms the
// release will actually be held to. A reader who sees only a runner code
// cannot tell a per-item check from a whole-release one, or a gate a person
// must answer from one an agent settles alone.

import { el } from "./universe_view_support.js";
import { ROLE_LABELS } from "./workflow_mechanics_data.js";

const RUNNER_LABELS = {
  auto: "Automatic",
  qa: "QA",
  "human-approval": "Approval",
  "ephemeral-deploy": "Preview deploy",
  "environment-activate": "Environment activation",
  "core-container-deploy": "Container deploy",
  "health-check": "Health check",
};

const VERDICT_PHRASES = {
  agent_only: "the agent decides",
  human_if_unsure: "a person decides when the agent is unsure",
  required_human: "a person decides",
};

const SCOPE_PHRASES = {
  item: "runs once per admitted item",
  run: "runs once for the whole release",
};

// The environment a warm-up stage reaches. The definition names it as the
// stage's connection; a server that does not serve that parameter still
// serves the later stages that act on "prod, as warm-up left it", which
// name the same environment.
function warmUpEnvironment(stage, stages) {
  if (stage.connection_env) return String(stage.connection_env);
  const follower = stages.find((other) => (
    other.target?.source_stage === stage.name && other.target?.environment
  ));
  return follower ? String(follower.target.environment) : "";
}

// What runs the stage, named the way a reader would say it rather than by
// the step runner's code. A parameter the server did not serve is left out
// rather than replaced with a placeholder word.
export function stageRunnerLabel(stage, stages = []) {
  const runner = String(stage.step_runner || "");
  const detail = (label, value) => (value ? `${label} · ${value}` : label);
  if (runner === "github-actions-workflow") return detail("GitHub Actions", stage.workflow);
  if (runner === "warm-up") return detail("Warm-up", warmUpEnvironment(stage, stages));
  if (runner === "ephemeral-verify") return detail("Preview verification", stage.workflow);
  if (!runner && stage.stage_kind === "qa") return "QA";
  return RUNNER_LABELS[runner] || runner || String(stage.stage_kind || "");
}

// A stage a person must answer: an approval step, or a QA verdict reserved
// for a human.
export function isPersonDecided(stage) {
  return stage.step_runner === "human-approval"
    || Boolean(stage.approvals)
    || stage.verdict?.mode === "required_human";
}

export function isQaStage(stage) {
  return stage.stage_kind === "qa" || stage.step_runner === "qa";
}

// Roles and actors read as one list of people. The mode is the difference
// between needing everyone and needing anyone, so it stays in the phrase.
export function peoplePhrase(policy, actorNames = {}) {
  const actors = (policy?.actors || []).map(
    (actorId) => actorNames[String(actorId)] || `actor ${actorId}`,
  );
  const roles = (policy?.roles || []).map((role) => ROLE_LABELS[role] || role);
  const people = [...new Set([...actors, ...roles])];
  if (!people.length) return "anyone with access";
  if (people.length === 1) return people[0];
  return `${policy?.mode === "all" ? "all of" : "any of"} ${people.join(", ")}`;
}

// Where the stage acts. A preview target names the stage that built it,
// because an ephemeral substrate has no name a reader could look up.
function targetPhrase(target) {
  if (!target) return "";
  if (target.kind === "run_preview") {
    return target.source_stage
      ? `the preview ${target.source_stage} built`
      : `a per-run preview (${target.capability})`;
  }
  const environment = `${target.environment} environment`;
  return target.source_stage
    ? `${environment}, as ${target.source_stage} left it`
    : environment;
}

function casesPhrase(cases) {
  if (!cases) return "";
  const keys = cases.case_keys || [];
  return keys.length
    ? `plan ${cases.plan_id} · ${keys.join(", ")}`
    : `plan ${cases.plan_id} · every case in the plan`;
}

function verdictPhrase(verdict, actorNames) {
  if (!verdict) return "";
  const decision = VERDICT_PHRASES[verdict.mode] || String(verdict.mode);
  if (verdict.mode === "agent_only") return decision;
  return `${decision} — ${peoplePhrase(verdict.reviewers, actorNames)}`;
}

// Being told a release failed is not the same as being asked to rule on it,
// so notification stays its own line.
function notificationPhrase(notification, actorNames) {
  if (!notification?.enabled) return "";
  const recipients = notification.recipients || {};
  const addressed = (recipients.actors?.length || recipients.roles?.length)
    ? peoplePhrase(recipients, actorNames)
    : "";
  return [
    ...(recipients.item_owners ? ["each item's owner"] : []),
    ...(addressed ? [addressed] : []),
  ].join(", ");
}

// The lines one stage contributes, in the order a reader asks for them.
export function stageFacts(stage, actorNames = {}) {
  return [
    ["Scope", SCOPE_PHRASES[stage.scope] || ""],
    ["Runs on", targetPhrase(stage.target)],
    ["Cases", casesPhrase(stage.cases)],
    ["Verdict", verdictPhrase(stage.verdict, actorNames)],
    ["Approvers", stage.approvals ? peoplePhrase(stage.approvals, actorNames) : ""],
    ["Notify", notificationPhrase(stage.notification, actorNames)],
  ].filter(([, value]) => value);
}

export function stageFactList(documentNode, stage, actorNames) {
  const facts = stageFacts(stage, actorNames);
  if (!facts.length) return null;
  const list = el(documentNode, "dl", "delivery-flow-stage-facts");
  for (const [label, value] of facts) {
    list.appendChild(el(documentNode, "dt", null, label));
    list.appendChild(el(documentNode, "dd", null, value));
  }
  return list;
}
