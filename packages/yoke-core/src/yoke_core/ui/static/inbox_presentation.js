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

// The named destinations a row offers, and the only things in it that
// navigate. The row itself used to be one big link, which made every word of
// the decision unselectable: a reader could not copy an item ref, a run id or
// a reason out of the thing they were being asked to judge. Linking the
// identifiers instead keeps the prose as prose.
export function decisionLinks(row) {
  const facts = row.subject_context || {};
  const links = [];
  const itemLink = (ref) => {
    const href = itemDrillInHref({ projectId: row.project_id, publicRef: ref });
    if (ref && href) links.push({ label: String(ref), href });
  };
  if (row.kind === "lifecycle_transition_approval") itemLink(facts.item_ref);
  if (row.kind === "deployment_stage_approval" && facts.run_id) {
    links.push({
      label: String(facts.run_id),
      href: buildUniverseRoute("deployments", row.project_id),
    });
  }
  if (row.kind === "qa_needs_review") {
    const subject = facts.subject || {};
    itemLink(subject.item_ref);
    if (subject.deployment_run_id) {
      links.push({
        label: String(subject.deployment_run_id),
        href: buildUniverseRoute("deployments", row.project_id),
      });
    }
    if (facts.plan_id) {
      links.push({
        label: `QA plan ${facts.plan_id}`,
        href: buildUniverseRoute(
          "qa-plans", row.project_id, String(facts.plan_id),
        ),
      });
    }
  }
  if (row.kind === "machine_approval" && facts.machine) {
    links.push({
      label: String(facts.machine),
      href: buildUniverseRoute("machines", null),
    });
  }
  return links;
}

// Where the ask came from, in the words of the thing that asked. Each kind
// reads its own persisted origin fact rather than a summary string: the
// lifecycle gate stores WHICH policy selected the approval, and rendering
// that as `workflow_posture.approval_on_done` handed a reader a config key
// they have no way to act on.
export function decisionOrigin(row) {
  const facts = row.subject_context || {};
  if (row.kind === "lifecycle_transition_approval") {
    const stage = facts.to_stage || "the next stage";
    if (facts.approval_source?.kind === "item_posture") {
      return `This item asks for approval to reach ${stage}. Its workflow `
        + "does not require one — the approval was selected on this item.";
    }
    return `Every ${facts.workflow_id || "workflow"} item needs approval to `
      + `reach ${stage}; this is that workflow's default, not a setting on `
      + "this item.";
  }
  if (row.kind === "deployment_stage_approval") {
    return `The ${facts.flow?.name || "deployment"} flow declares its `
      + `${facts.stage || "next"} stage gated, so the pipeline stops here `
      + "for a person.";
  }
  if (row.kind === "qa_needs_review") {
    const subject = facts.subject || {};
    if (subject.kind === "deployment_run") {
      return `An agent ran this check against ${
        subject.deployment_run_id
      } and returned no verdict, so recording one is a person's job.`;
    }
    return "An agent ran this check and returned no verdict, so recording "
      + "one is a person's job.";
  }
  if (row.kind === "machine_approval") {
    return "A machine asked to join this organization and cannot act until "
      + "an admin admits it.";
  }
  return "";
}

// Why THIS reader is holding it, and who else could answer instead. Both are
// read from live membership, so a row never tells someone they are the only
// approver when a colleague holds the same role.
export function decisionEligibility(row) {
  const progress = row.approval_progress || {};
  const deciders = Array.isArray(row.deciders) ? row.deciders : [];
  const others = deciders.filter((decider) => !decider.is_you);
  const you = row.asked_of_you
    ? "You were asked by name."
    : row.authority_reason
      ? `You can answer because you hold ${row.authority_reason}.`
      : "";
  const describe = (decider) => (
    decider.via === "named"
      ? decider.label
      : `${decider.label} (${decider.via})`
  );
  const required = Number(progress.required || 0);
  const settles = progress.mode === "all"
    ? `Every approver must answer: ${Number(progress.satisfied || 0)} of ${
      required
    } recorded${
      (progress.outstanding || []).length
        ? `, waiting on ${(progress.outstanding || []).join(", ")}`
        : ""
    }.`
    : "Any one approver settles it.";
  return {
    you,
    others: others.map(describe),
    settles: deciders.length || required ? settles : "",
  };
}

export function decisionProgressText(row) {
  const progress = row.approval_progress || {};
  const required = Number(progress.required || 0);
  if (required < 2) return "";
  return `${Number(progress.satisfied || 0)} of ${required} approvals`;
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
      facts.flow?.name,
    ];
  },
  qa_needs_review(facts) {
    return [
      facts.plan_name,
      facts.method_name,
    ];
  },
  lifecycle_transition_approval(facts) {
    // The item's own title, not the policy that gated it: which policy asked
    // is prose the body carries, and naming its config entry here told the
    // reader a settings key instead of what they are looking at.
    return [facts.item_title];
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
//
// A deployment stage reads its title from the classification the request
// froze rather than composing one from the shipping destination, which is
// what titled an approval that deploys nothing "Deploy to merge-only". A
// request recorded before that classification existed gets the neutral
// title, not its own stored one: that stored sentence is the invented
// consequence, and the honest answer for it is that nobody knows.
const TITLE_BUILDERS = {
  deployment_stage_approval(facts) {
    const stage = String(facts.stage || "next stage").replaceAll("-", " ");
    return `Approve ${stage}`;
  },
  qa_needs_review(facts) {
    const subject = facts.case_name || facts.plan_name;
    return subject ? `Review ${subject}` : "";
  },
  lifecycle_transition_approval(facts) {
    if (!facts.item_ref) return "";
    return `Approve ${facts.item_ref} ${facts.to_stage || "transition"}`;
  },
};

export function decisionSummary(row) {
  const facts = row.subject_context || {};
  if (row.kind === "deployment_stage_approval") {
    const effect = facts.release_effect || {};
    if (effect.consequence === "deploys_nothing") {
      return "Approval only — deploys nothing. Resolving this lets the run continue.";
    }
    if (effect.consequence !== "deploys") {
      return "Deployment effect is unknown. Treat this as a deploy decision.";
    }
    const carried = facts.carried;
    const known = carried?.derivation?.contents_known;
    const count = (carried?.items || []).length + (carried?.commits || []).length;
    const target = facts.shipping?.target_environment || "an environment";
    return known
      ? `Deploys ${count} ${count === 1 ? "change" : "changes"} to ${target}.`
      : `Deploys to ${target}; release contents are unknown.`;
  }
  if (row.kind === "lifecycle_transition_approval") {
    return `Moves the item to ${facts.to_stage || "its next stage"}. Deploys nothing.`;
  }
  if (row.kind === "qa_needs_review") {
    const count = Number(facts.artifact_count || 0);
    return count
      ? `Human verdict needed. ${count} ${count === 1 ? "artifact" : "artifacts"} attached.`
      : "Human verdict needed. No evidence is attached.";
  }
  return "";
}

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
  decisionEligibility,
  decisionLinks,
  decisionOrigin,
  decisionProgressText,
  decisionSummary,
  decisionSubtitle,
  decisionTitle,
  subjectHref,
  yourDecisionText,
};
