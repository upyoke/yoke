import { buildUniverseRoute } from "./universe_navigation.js";
import { itemDrillInHref } from "./universe_item_routes.js";

export const KIND_PRESENTATION = {
  deployment_stage_approval: { icon: "⬈", fallback: "Approve deployment stage" },
  qa_needs_review: { icon: "◉", fallback: "QA evidence needs your review" },
  lifecycle_transition_approval: { icon: "≣", fallback: "Approve lifecycle transition" },
  machine_approval: { icon: "⚇", fallback: "Approve a new machine" },
};

export const ACTION_LABELS = {
  approve: "Approve",
  reject: "Reject",
  waive: "Waive",
  deny: "Deny",
  request_changes: "Request changes",
};

export const ACTION_RANK = {
  waive: 0,
  reject: 1,
  deny: 1,
  request_changes: 1,
  approve: 2,
};

export function subjectHref(row) {
  const facts = row.subject_context || {};
  if (facts.href) return String(facts.href);
  if (row.kind === "deployment_stage_approval") {
    return buildUniverseRoute("deployments", row.project_id);
  }
  if (row.kind === "qa_needs_review") {
    if (facts.plan_id) {
      return buildUniverseRoute(
        "qa-plans", row.project_id, String(facts.plan_id),
      );
    }
    return buildUniverseRoute("qa-activity", row.project_id);
  }
  if (row.kind === "lifecycle_transition_approval") {
    return itemDrillInHref({
      projectId: row.project_id,
      publicRef: facts.item_ref,
    }) || buildUniverseRoute("items", row.project_id);
  }
  if (row.kind === "machine_approval") {
    // A machine approval is answered beside the machine it admits, and it
    // is org-scoped, so no project narrows the destination.
    return buildUniverseRoute("machines", null);
  }
  return buildUniverseRoute("inbox", row.project_id);
}

export function decisionProgressText(row) {
  const progress = row.approval_progress || {};
  const required = Number(progress.required || 0);
  if (required < 2) return "";
  const count = `${Number(progress.satisfied || 0)} of ${required}`;
  const waiting = (progress.outstanding || []).join(", ");
  return waiting ? `${count}, waiting on ${waiting}` : count;
}

export function yourDecisionText(row) {
  if (!row.decided_by_you) return "";
  const action = row.your_decision?.action;
  return `you chose ${ACTION_LABELS[action] || action || "an action"}`;
}

export function decisionSubtitle(row) {
  const facts = row.subject_context || {};
  const details = [];
  const trailing = [];
  if (facts.summary) details.push(facts.summary);
  else if (row.kind === "deployment_stage_approval") {
    if (facts.run_id) details.push(facts.run_id);
    if (facts.stage) details.push(`${facts.stage} stage`);
  } else if (row.kind === "qa_needs_review") {
    for (const value of [
      facts.plan_name, facts.case_name, facts.method_name, facts.evidence_summary,
    ]) if (value) details.push(value);
  } else if (row.kind === "lifecycle_transition_approval") {
    if (facts.policy_summary) details.push(facts.policy_summary);
    else if (facts.transition) details.push(`${facts.transition} transition`);
  } else if (row.kind === "machine_approval") {
    details.push(facts.machine ? `machine ${facts.machine}` : "machine not named");
    details.push(
      facts.code ? `one-time code ${facts.code}` : "no one-time code delivered",
    );
    // Whoever installed Yoke on that machine keeps it once it is admitted:
    // approving never transfers ownership to the approver.
    if (row.originator_actor_label) {
      details.push(`requested by ${row.originator_actor_label}`);
    }
  }
  const progress = decisionProgressText(row);
  if (progress) trailing.push(progress);
  const decided = yourDecisionText(row);
  if (decided) trailing.push(decided);
  else if (row.asked_of_you) trailing.push("asked of you");
  else if (row.authority_reason) trailing.push(`you: ${row.authority_reason}`);
  return {
    leading: details.join(" · "),
    timeVerb: "requested",
    trailing: trailing.join(" · "),
  };
}

export function decisionTitle(row) {
  const facts = row.subject_context || {};
  if (facts.title) return String(facts.title);
  const presentation = KIND_PRESENTATION[row.kind] || {};
  if (facts.item_ref && row.kind === "lifecycle_transition_approval") {
    return `${facts.item_ref} — approve the ${facts.transition || "next"} transition`;
  }
  if (facts.case_name && row.kind === "qa_needs_review") {
    return `${facts.case_name} needs your review`;
  }
  return presentation.fallback || row.subject_key;
}

export const inboxPresentation = {
  decisionProgressText,
  decisionSubtitle,
  decisionTitle,
  subjectHref,
  yourDecisionText,
};
