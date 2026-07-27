import { buildUniverseRoute } from "./universe_navigation.js";

export const KIND_PRESENTATION = {
  deployment_stage_approval: { icon: "⬈", fallback: "Approve deployment stage" },
  qa_needs_review: { icon: "◉", fallback: "QA evidence needs your review" },
  lifecycle_transition_approval: { icon: "≣", fallback: "Approve lifecycle transition" },
  machine_approval: { icon: "⚇", fallback: "Approve a new machine" },
  strategy_revision_review: { icon: "❖", fallback: "Review a strategy revision" },
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
    return buildUniverseRoute("delivery", row.project_id, "runs");
  }
  if (row.kind === "qa_needs_review") {
    if (facts.plan_id) {
      return buildUniverseRoute(
        "qa", row.project_id, "plans", String(facts.plan_id),
      );
    }
    return buildUniverseRoute("qa", row.project_id, "activity");
  }
  if (row.kind === "lifecycle_transition_approval") {
    const item = String(facts.item_ref || facts.item_id || "");
    return buildUniverseRoute("items", row.project_id, item || null);
  }
  if (row.kind === "machine_approval") {
    return buildUniverseRoute("access", null);
  }
  if (row.kind === "strategy_revision_review") {
    return buildUniverseRoute("strategy", row.project_id, facts.slug || null);
  }
  return buildUniverseRoute("inbox", row.project_id);
}

export function decisionSubtitle(row) {
  const facts = row.subject_context || {};
  const details = [];
  const trailing = [];
  let timeVerb = "requested";
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
  } else if (row.kind === "machine_approval" && facts.code) {
    details.push(`one-time code ${facts.code}`);
  } else if (row.kind === "strategy_revision_review") {
    if (facts.author_label) details.push(`revision by ${facts.author_label}`);
    timeVerb = "";
    trailing.push("the doc stays live while this waits");
  }
  if (row.asked_of_you) trailing.push("asked of you");
  else if (row.authority_reason) trailing.push(`you: ${row.authority_reason}`);
  return {
    leading: details.join(" · "),
    timeVerb,
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
  if (facts.slug && row.kind === "strategy_revision_review") {
    return `${facts.slug} — review a revision`;
  }
  return presentation.fallback || row.subject_key;
}

export function notificationPresentation(row) {
  const facts = (row.event && row.event.context) || {};
  if (facts.title) {
    return { title: facts.title, subtitle: facts.summary || row.reason };
  }
  if (row.notification_kind === "deployment_run_completed") {
    const target = facts.target_env || "Deployment";
    return {
      title: `${target} deploy completed`,
      subtitle: [facts.run_id, row.event_outcome]
        .filter(Boolean).join(" · "),
    };
  }
  if (row.notification_kind === "item_block_state_changed") {
    const state = row.event_name === "ItemUnblocked" ? "unblocked" : "blocked";
    return {
      title: `${facts.item_ref || "Item"} ${state}`,
      subtitle: [facts.reason].filter(Boolean).join(" · "),
    };
  }
  const title = facts.kind === "deployment_stage_approval"
    ? "Your stage approval was resolved"
    : "Your decision request was resolved";
  const action = {
    approve: "approved",
    reject: "rejected",
    waive: "waived",
    deny: "denied",
    request_changes: "changes requested",
  }[facts.action];
  const resolution = facts.resolution_actor_label
    ? `${action || row.reason} by ${facts.resolution_actor_label}`
    : (action || row.reason);
  return { title, subtitle: resolution };
}

export function notificationHref(row) {
  const facts = (row.event && row.event.context) || {};
  if (facts.href) return String(facts.href);
  if (row.notification_kind === "deployment_run_completed") {
    return buildUniverseRoute("delivery", row.project_id, "runs");
  }
  if (row.notification_kind === "item_block_state_changed") {
    const item = facts.item_ref || facts.item_id;
    if (item) return buildUniverseRoute("items", row.project_id, String(item));
  }
  if (facts.slug) {
    return buildUniverseRoute("strategy", row.project_id, String(facts.slug));
  }
  return buildUniverseRoute("inbox", row.project_id);
}

export const inboxPresentation = {
  decisionSubtitle,
  decisionTitle,
  notificationPresentation,
  notificationHref,
  subjectHref,
};
