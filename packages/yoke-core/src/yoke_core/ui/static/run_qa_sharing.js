// One grouping rule for every QA surface. A plan several carried items
// attach is checked once for the release, so its checks are drawn once under
// Run QA, labelled with the items that share it; each sharing item only
// points at it. A removed member is drawn as removed with the checks its
// removal cancelled, never as open QA. The facts come from the run-scoped
// `qa.activity.list` read (`run_sharing`), so the run page, Shipping and the
// Inbox all draw from the same record.

import { el } from "./universe_view_support.js";

const EMPTY = Object.freeze({ shared_plans: [], removed_members: [] });

// The read's `run_sharing` merged into a Map keyed by run id.
export function collectRunSharing(target, runSharing) {
  for (const [runId, sharing] of Object.entries(runSharing || {})) {
    target.set(String(runId), sharing || EMPTY);
  }
  return target;
}

export function sharingFor(facts, runId) {
  return facts?.sharing?.get(String(runId || "")) || EMPTY;
}

// The shared plan a check's copy was materialized for, or null.
export function sharedPlanId(check) {
  const plan = check?.execution_target_json?.deployment?.shared_plan;
  return plan?.plan_id == null ? null : String(plan.plan_id);
}

function refs(plan) {
  return (plan.sharing_public_refs || []).map(String);
}

export function sharedPlanName(plan) {
  return String(plan.plan_name || plan.plan || `plan ${plan.plan_id}`);
}

export function sharedByLabel(plan) {
  const sharing = refs(plan);
  return sharing.length ? `Shared by ${sharing.join(", ")}` : "Shared";
}

export function memberSharedPlans(sharing, itemRef) {
  return (sharing?.shared_plans || []).filter(
    (plan) => refs(plan).includes(String(itemRef)));
}

export function removedMember(sharing, itemRef) {
  return (sharing?.removed_members || []).find(
    (entry) => String(entry.public_ref) === String(itemRef)) || null;
}

export function cancelledLabel(count) {
  const n = Number(count || 0);
  return `${n} check${n === 1 ? "" : "s"} cancelled`;
}

// Run QA's checks split into the release's own and one group per shared
// plan. A check of a plan this read does not name stays with the release's
// own, so nothing is dropped when the facts are absent.
export function groupRunChecks(checks, sharing) {
  const plans = new Map((sharing?.shared_plans || []).map(
    (plan) => [String(plan.plan_id), { plan, checks: [] }]));
  const own = [];
  for (const check of checks || []) {
    const group = plans.get(sharedPlanId(check));
    if (group) group.checks.push(check);
    else own.push(check);
  }
  return {
    own,
    groups: [...plans.values()].filter((group) => group.checks.length).map(
      ({ plan, checks: planChecks }) => ({
        label: `${sharedPlanName(plan)} · ${sharedByLabel(plan)}`, checks: planChecks,
      })),
  };
}

// "shares Installer campaign (28) — see Run QA", one line per shared plan.
export function appendSharedPlanPointers(documentNode, host, plans) {
  for (const plan of plans) {
    host.appendChild(el(documentNode, "p", "item-qa-shared-pointer",
      `shares ${sharedPlanName(plan)} (${Number(plan.case_count || 0)}) — see Run QA`));
  }
}

// The tile an item keeps when every check it owes is a shared plan's.
export function sharedOnlyVerdict(plans) {
  return `0 own checks, shares ${plans.map(sharedPlanName).join(", ")}`;
}

// Item QA for an item whose every check is a shared plan's: the tile stays,
// says it owns none, and points at Run QA. The section is a direct child of
// the member grid, so it takes the same full row as the diagnostic note;
// otherwise the title column collapses to one letter per line.
export function appendSharedOnlyItemQa(documentNode, host, plans) {
  const section = el(
    documentNode, "section",
    "run-qa-section item-qa-section carried-item-qa-diagnostic",
  );
  const head = el(documentNode, "div", "run-qa-head");
  head.appendChild(el(documentNode, "h4", null, "Item QA"));
  head.appendChild(el(documentNode, "span", "run-verdict", sharedOnlyVerdict(plans)));
  section.appendChild(head);
  appendSharedPlanPointers(documentNode, section, plans);
  host.appendChild(section);
  return { node: section, requestIds: new Set() };
}

// A member removed from this run is drawn as removed, with what removal
// cancelled, instead of Item QA; null for a current member. The note is a
// direct child of the member grid and takes the same full row.
export function appendRemovedItemQa(documentNode, host, sharing, itemRef) {
  const entry = removedMember(sharing, itemRef);
  if (!entry) return null;
  const note = el(documentNode, "p", "carried-item-removed carried-item-qa-diagnostic",
    `Removed from this release · ${cancelledLabel(entry.cancelled_count)}`);
  host.appendChild(note);
  return { node: note, requestIds: new Set() };
}

export const runQaSharing = {
  appendSharedPlanPointers,
  cancelledLabel,
  collectRunSharing,
  groupRunChecks,
  memberSharedPlans,
  appendRemovedItemQa,
  appendSharedOnlyItemQa,
  removedMember,
  sharedByLabel,
  sharedOnlyVerdict,
  sharedPlanId,
  sharedPlanName,
  sharingFor,
};
