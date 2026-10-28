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
  return sharing.length ? `Covers: ${sharing.join(", ")}` : "Shared";
}

export function memberSharedPlans(sharing, itemRef) {
  return (sharing?.shared_plans || []).filter(
    (plan) => refs(plan).includes(String(itemRef)));
}

export function cancelledLabel(count) {
  const n = Number(count || 0);
  return `${n} check${n === 1 ? "" : "s"} cancelled`;
}

// Run QA's checks split into the release's own and one group per shared
// plan. A check of a plan this read does not name stays with the release's
// own, so nothing is dropped when the facts are absent. A pending plan —
// shared before item-qa copies it — draws its cases as not-started checks.
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
    groups: [...plans.values()].map(({ plan, checks: planChecks }) => ({
      label: `${sharedPlanName(plan)} · ${sharedByLabel(plan)}`,
      checks: planChecks.length ? planChecks : (plan.cases || []),
    })).filter((group) => group.checks.length),
  };
}

// "Shared: Installer campaign — see Run QA": the shared-only tile names
// every plan; an item with its own checks gets one pointer per plan. Run QA
// already names the items each plan covers and counts its checks.
export function sharedOnlyVerdict(plans) {
  return `Shared: ${plans.map(sharedPlanName).join(", ")} — see Run QA`;
}

export function appendSharedPlanPointers(documentNode, host, plans) {
  for (const plan of plans) {
    host.appendChild(el(documentNode, "p", "item-qa-shared-pointer",
      sharedOnlyVerdict([plan])));
  }
}

// Item QA for an item whose every check is a shared plan's: one tile that
// points at Run QA, with no pointer line repeating it. The section is a
// direct child of the member grid, so it takes the same full row as the
// diagnostic note; otherwise the title column collapses to one letter per
// line.
export function appendSharedOnlyItemQa(documentNode, host, plans) {
  const section = el(
    documentNode, "section",
    "run-qa-section item-qa-section carried-item-qa-diagnostic",
  );
  const head = el(documentNode, "div", "run-qa-head");
  head.appendChild(el(documentNode, "h4", null, "Item QA"));
  head.appendChild(el(documentNode, "span", "run-verdict", sharedOnlyVerdict(plans)));
  section.appendChild(head);
  host.appendChild(section);
  return { node: section, requestIds: new Set() };
}

export const runQaSharing = {
  appendSharedPlanPointers,
  cancelledLabel,
  collectRunSharing,
  groupRunChecks,
  memberSharedPlans,
  appendSharedOnlyItemQa,
  sharedByLabel,
  sharedOnlyVerdict,
  sharedPlanId,
  sharedPlanName,
  sharingFor,
};
