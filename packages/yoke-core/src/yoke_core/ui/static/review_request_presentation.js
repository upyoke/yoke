// The plain words on a review request card, read from the request row.
//
// Every string here traces to a served field: the kind, the frozen
// subject_context, live deciders and approval progress, and the reader's own
// recorded decision. Nothing is composed from a guess about what a stage
// does or who might hold a role.

import {
  ACTION_LABELS,
  decisionSubtitle,
  decisionSummary,
} from "./inbox_presentation.js";

export const KIND_LABELS = {
  deployment_stage_approval: "Release approval",
  lifecycle_transition_approval: "Work approval",
  qa_needs_review: "QA review",
};

const DECIDED_LABELS = {
  approve: "Approved",
  reject: "Rejected",
  waive: "Waived",
  deny: "Denied",
  request_changes: "Changes requested",
};

export function kindLabel(row) {
  return KIND_LABELS[row.kind] || "Decision";
}

// What resolving this does, in one sentence. The QA card carries its own
// body instead: what was checked and what the agent said are the effect.
export function effectLine(row) {
  if (row.kind === "qa_needs_review") return "";
  const effect = row.subject_context?.release_effect;
  if (effect && effect.consequence === "deploys_nothing") {
    return "Deploys nothing. Approving lets the run finish.";
  }
  return decisionSummary(row);
}

// The identifying facts under the title: the flow and run for a release,
// the plan and method for a review, the item's own title for a transition.
export function contextLine(row) {
  const facts = row.subject_context || {};
  const parts = [decisionSubtitle(row).leading];
  // The destination is named only for a release that reaches one: a gate
  // that deploys nothing has no "to" — its no-destination label is the
  // invented consequence this line must never read out.
  if (
    row.kind === "deployment_stage_approval"
    && facts.release_effect?.consequence === "deploys"
    && facts.shipping?.target_environment
  ) {
    parts.push(`to ${facts.shipping.target_environment}`);
  }
  return parts.map((value) => (value == null ? "" : String(value)))
    .filter(Boolean).join(" · ");
}

export function decidedLabel(row) {
  if (!row.decided_by_you) return "";
  const action = row.your_decision?.action;
  return DECIDED_LABELS[action] || (action ? ACTION_LABELS[action] || action : "Decided");
}

// Who settles this, told from live membership and the request's own mode.
// An every-approver gate counts; a single-approver gate names the people —
// or the role, when the people are whoever holds it today.
export function reviewerLine(row) {
  const progress = row.approval_progress || {};
  const deciders = Array.isArray(row.deciders) ? row.deciders : [];
  const required = Number(progress.required || 0);
  const decided = decidedLabel(row);
  if (progress.mode === "all" && (required > 1 || deciders.length > 1)) {
    const outstanding = (progress.outstanding || []).filter(Boolean);
    return [
      decided ? `You ${decided.toLowerCase()}` : "All must approve",
      `${Number(progress.satisfied || 0)} of ${required || deciders.length}`,
      outstanding.length ? `waiting on ${outstanding.join(", ")}` : "",
    ].filter(Boolean).join(" · ");
  }
  if (decided) return `You ${decided.toLowerCase()}`;
  if (!deciders.length) {
    return row.authority_reason ? `You can approve as ${row.authority_reason}` : "";
  }
  const named = deciders.filter((decider) => decider.via === "named");
  if (named.length === deciders.length) {
    const labels = deciders.map((decider) => (decider.is_you ? "you" : decider.label));
    return labels.length === 1
      ? `${labels[0] === "you" ? "You" : labels[0]} can approve`
      : `Any of ${labels.join(", ")} can approve`;
  }
  const roles = [...new Set(
    deciders.filter((decider) => decider.via !== "named").map((decider) => decider.via),
  )];
  const people = named.map((decider) => (decider.is_you ? "you" : decider.label));
  return `Any ${[...roles, ...people].join(" or ")} can approve`;
}

// The artifacts a card shows, normalized across kinds: a QA review carries
// the run's own artifacts; a release or work approval carries the subject's
// latest screenshot evidence, which the producer froze beside its state.
export function evidenceOf(row) {
  const facts = row.subject_context || {};
  if (row.kind === "qa_needs_review") {
    return {
      artifacts: Array.isArray(facts.artifacts) ? facts.artifacts : [],
      requirementId: facts.requirement_id ?? null,
      state: facts.evidence_state || "",
      note: "",
    };
  }
  const evidence = facts.evidence || {};
  const notes = {
    failed: "This evidence includes a failed QA result.",
    stale: "These screenshots cover an older revision than this decision.",
    revision_unknown: "The screenshot revision was not recorded.",
  };
  return {
    artifacts: Array.isArray(evidence.screenshots) ? evidence.screenshots : [],
    requirementId: null,
    state: evidence.state || "",
    note: notes[evidence.state] || "",
  };
}

// What a QA review is a review OF: the subject, the run, the revision, what
// was expected, and the agent's own words for why it could not decide.
export function qaFacts(row) {
  const facts = row.subject_context || {};
  const subject = facts.subject || {};
  const checked = [];
  if (subject.kind === "deployment_run" && subject.deployment_run_id) {
    checked.push(String(subject.deployment_run_id));
    if (subject.target_environment) checked.push(`released to ${subject.target_environment}`);
  } else if (subject.item_ref) {
    checked.push([subject.item_ref, subject.item_title].filter(Boolean).join(" · "));
  }
  if (facts.run_id != null) checked.push(`run ${facts.run_id}`);
  if (subject.qa_phase) checked.push(String(subject.qa_phase));
  checked.push(facts.code_revision
    ? `revision ${String(facts.code_revision).slice(0, 12)}`
    : "revision not recorded");
  return [
    ["Checked", checked.join(" · ")],
    ["Expected", facts.expected_outcome ? String(facts.expected_outcome) : ""],
    ["Agent said", facts.verdict_reason ? String(facts.verdict_reason) : ""],
  ].filter(([, value]) => value);
}

export const reviewRequestPresentation = {
  KIND_LABELS,
  contextLine,
  decidedLabel,
  effectLine,
  evidenceOf,
  kindLabel,
  qaFacts,
  reviewerLine,
};
