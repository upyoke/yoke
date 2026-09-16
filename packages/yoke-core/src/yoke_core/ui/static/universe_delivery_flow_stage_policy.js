// What a release stage does beyond carrying a name: the kind of work it is,
// the scope it operates at, the target it acts on, and — for a QA stage —
// who decides its verdict versus who is only told the result.
//
// Every run freezes the definition it references, so these are the terms the
// release will actually be held to. A reader who can only see stage names
// cannot tell a per-item check from a whole-release one, or a gate a person
// must answer from one an agent settles alone; both mistakes are only
// discovered once the run is already halted on them.

import { el } from "./universe_view_support.js";
import { ROLE_LABELS } from "./workflow_mechanics_data.js";

const VERDICT_PHRASES = {
  agent_only: "the agent decides",
  human_if_unsure: "a person decides when the agent is unsure",
  required_human: "a person decides, always",
};

const SCOPE_PHRASES = {
  item: "runs once per admitted item",
  run: "runs once for the whole release",
};

// Roles and actors read as one addressee list. The mode is the difference
// between needing everyone and needing anyone, so it stays in the phrase
// rather than being flattened into a comma list.
export function addresseePhrase(policy) {
  const who = [
    ...(policy?.roles || []).map((role) => ROLE_LABELS[role] || role),
    ...(policy?.actors || []).map((actorId) => `actor ${actorId}`),
  ];
  if (!who.length) return "";
  return who.join(policy?.mode === "all" ? " and " : " or ");
}

// Where the stage acts. A preview target names the stage that built it
// rather than an environment, because an ephemeral substrate has no name a
// reader could look up anywhere else.
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

// Verdict authority and notification are deliberately two lines. Being told
// a release failed is not the same as being asked to rule on it, and a
// definition that blurs them is how a review nobody owns goes unanswered.
function verdictPhrase(verdict) {
  if (!verdict) return "";
  const decision = VERDICT_PHRASES[verdict.mode] || String(verdict.mode);
  const reviewers = addresseePhrase(verdict.reviewers);
  return reviewers ? `${decision} — ${reviewers}` : decision;
}

function notificationPhrase(notification) {
  if (!notification?.enabled) return "";
  const recipients = notification.recipients || {};
  const addressed = addresseePhrase(recipients);
  const who = [
    ...(recipients.item_owners ? ["each item's owner"] : []),
    ...(addressed ? [addressed] : []),
  ];
  return who.join(", ");
}

// The lines one stage contributes, in the order a reader asks for them:
// what it is, where it acts, what it checks, who rules on it, who hears.
function policyLines(stage) {
  const approvers = addresseePhrase(stage.approvals);
  return [
    ["Scope", SCOPE_PHRASES[stage.scope] || ""],
    ["Runs on", targetPhrase(stage.target)],
    ["Cases", casesPhrase(stage.cases)],
    ["Verdict", verdictPhrase(stage.verdict)],
    ["Notifies", notificationPhrase(stage.notification)],
    ["Approval", approvers],
  ].filter(([, value]) => value);
}

// The badge a reader scans for first. QA stages are called out by kind
// because a gate is the thing worth spotting in a pipeline; every other
// stage is labelled by its step runner, which says the same thing more
// precisely — "ephemeral-deploy" is already, unmistakably, execution.
export function stageKindLabel(stage) {
  if (stage.stage_kind === "qa") return "QA";
  return String(stage.step_runner || stage.stage_kind || "");
}

export function stagePolicyList(documentNode, stage) {
  const lines = policyLines(stage);
  if (!lines.length) return null;
  const list = el(documentNode, "dl", "delivery-flow-stage-policy");
  for (const [label, value] of lines) {
    const row = el(documentNode, "div", "delivery-flow-stage-policy-row");
    row.appendChild(el(documentNode, "dt", null, label));
    row.appendChild(el(documentNode, "dd", null, value));
    list.appendChild(row);
  }
  return list;
}
