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

// Each kind's identifying facts, read from the payload its own gate writes.
// These builders are the single place that knows a subject_context shape, so
// a producer that changes its facts breaks here rather than silently
// rendering a row that describes nothing.
const SUBTITLE_BUILDERS = {
  deployment_stage_approval(facts) {
    return [
      facts.run_id,
      facts.flow?.name ? `flow ${facts.flow.name}` : "",
      facts.stage ? `stage ${facts.stage}` : "",
    ];
  },
  qa_needs_review(facts) {
    return [
      facts.plan_name,
      facts.method_name,
      facts.run_id ? `run ${facts.run_id}` : "",
      "undetermined",
    ];
  },
  lifecycle_transition_approval(facts) {
    const version = facts.workflow_id
      ? `${facts.workflow_id}${
        facts.workflow_version_id ? ` v${facts.workflow_version_id}` : ""
      }`
      : "";
    return [version, facts.approval_source?.entry];
  },
  machine_approval(facts, row) {
    return [
      facts.machine ? `machine ${facts.machine}` : "machine not named",
      facts.code ? `one-time code ${facts.code}` : "no one-time code delivered",
      // Whoever installed Yoke on that machine keeps it once it is admitted:
      // approving never transfers ownership to the approver.
      row.originator_actor_label ? `requested by ${row.originator_actor_label}` : "",
    ];
  },
};

export function decisionSubtitle(row) {
  const facts = row.subject_context || {};
  const build = SUBTITLE_BUILDERS[row.kind];
  const details = (build ? build(facts, row) : [])
    .map((value) => (value == null ? "" : String(value)))
    .filter(Boolean);
  const trailing = [];
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

// Titles are composed from the facts rather than read from the stored
// `title` string. Every producer writes one, and QA's is a fixed sentence
// that names no case, so preferring the stored value made a reviewer's list
// of pending reviews read identically for all of them.
const TITLE_BUILDERS = {
  deployment_stage_approval(facts) {
    const target = facts.shipping?.target_environment;
    if (!target) return "";
    return `Deploy to ${target} — approve the ${facts.stage || "next"} stage`;
  },
  qa_needs_review(facts) {
    const subject = facts.case_name || facts.plan_name;
    return subject ? `${subject} needs your review` : "";
  },
  lifecycle_transition_approval(facts) {
    if (!facts.item_ref) return "";
    return `${facts.item_ref} — approve the ${facts.to_stage || "next"} transition`;
  },
};

export function decisionTitle(row) {
  const facts = row.subject_context || {};
  const build = TITLE_BUILDERS[row.kind];
  const composed = build ? build(facts) : "";
  if (composed) return composed;
  if (facts.title) return String(facts.title);
  const presentation = KIND_PRESENTATION[row.kind] || {};
  return presentation.fallback || row.subject_key;
}

export const inboxPresentation = {
  decisionProgressText,
  decisionSubtitle,
  decisionTitle,
  subjectHref,
  yourDecisionText,
};
