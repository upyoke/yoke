// One grouping rule for every QA surface. Each post-deploy plan an item
// attaches runs once per release as a plan group, so its checks are drawn
// once under Run QA, labelled with the items it answers; each of those items
// only points at it. Groups are keyed by `group_id`, never by plan id: a run
// may hold a closed and an open group of one plan. A removed member is drawn
// as removed with the checks its removal cancelled, never as open QA. The
// facts come from the run-scoped `qa.activity.list` read (`run_sharing`), so
// the run page, Shipping and the Inbox all draw from the same record.

import { el } from "./universe_view_support.js";

const EMPTY = Object.freeze({ plan_groups: [], removed_members: [] });

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

// The plan group a memberless check belongs to, or null for any other check.
export function planGroupId(check) {
  if (check?.deployment_member_public_ref != null) return null;
  const marker = check?.execution_target_json?.deployment?.shared_plan;
  return marker?.group_id == null ? null : String(marker.group_id);
}

// A pending plan has no group yet; it is keyed by its plan until one forms.
function groupKey(group) {
  return group.group_id == null ? `pending:${group.plan_id}` : String(group.group_id);
}

function refs(group) {
  return (group.sharing_public_refs || []).map(String);
}

export function sharedPlanName(group) {
  return String(group.plan_name || group.plan || `plan ${group.plan_id}`);
}

export function sharedByLabel(group) {
  const sharing = refs(group);
  return sharing.length ? `Covers: ${sharing.join(", ")}` : "Plan group";
}

// The plan groups that answer one item on this run.
export function itemPlanGroups(sharing, itemRef) {
  return (sharing?.plan_groups || []).filter(
    (group) => refs(group).includes(String(itemRef)));
}

export function cancelledLabel(count) {
  const n = Number(count || 0);
  return `${n} check${n === 1 ? "" : "s"} cancelled`;
}

// Run QA's checks split into the release's own and one entry per plan
// group, keyed by group id. A check of a group this read does not name stays
// with the release's own, so nothing is dropped when the facts are absent. A
// pending plan draws its cases as not-started checks; a closed group of an
// earlier run is labelled with that run and draws no checks of this run.
export function groupRunChecks(checks, sharing) {
  const all = sharing?.plan_groups || [];
  const groups = new Map(all.map((group) => [groupKey(group), { group, checks: [] }]));
  const own = [];
  for (const check of checks || []) {
    const entry = groups.get(planGroupId(check));
    if (entry) entry.checks.push(check);
    else own.push(check);
  }
  return {
    own,
    groups: [...groups.values()].map(({ group, checks: groupChecks }) => ({
      label: groupLabel(group, all),
      checks: groupChecks.length ? groupChecks : (group.cases || []),
      earlier: group.earlier_run_id != null,
    })).filter((entry) => entry.checks.length || entry.earlier)
      .map(({ label, checks: groupChecks }) => ({ label, checks: groupChecks })),
  };
}

// "Release smoke · group 2 · Covers: YOK-1, YOK-2". A plan with more than one
// group in this run names each group's sequence; an earlier run's closed group
// reads "Passed in run-…" instead.
export function groupLabel(group, all = []) {
  const parts = [sharedPlanName(group)];
  const here = (other) => other.group_id && other.earlier_run_id == null;
  const siblings = all.filter((other) => other.plan_id === group.plan_id && here(other));
  if (group.earlier_run_id) parts.push(`Passed in ${group.earlier_run_id}`);
  else if (siblings.length > 1 && here(group)) {
    parts.push(`group ${String(group.group_id).split(":").pop()}`);
  }
  parts.push(sharedByLabel(group));
  return parts.join(" · ");
}

// "Plan group: Installer campaign — see Run QA": the plan-group-only tile
// names every group; an item with its own item cases gets one pointer per
// group. Run QA already names the items each group covers and counts its checks.
export function sharedOnlyVerdict(groups) {
  const noun = groups.length === 1 ? "Plan group" : "Plan groups";
  return `${noun}: ${groups.map(sharedPlanName).join(", ")} — see Run QA`;
}

export function appendSharedPlanPointers(documentNode, host, plans) {
  for (const plan of plans) {
    host.appendChild(el(documentNode, "p", "item-qa-shared-pointer",
      sharedOnlyVerdict([plan])));
  }
}

// Item QA for an item whose every check is a plan group's: one tile that
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
  groupLabel,
  groupRunChecks,
  itemPlanGroups,
  appendSharedOnlyItemQa,
  sharedByLabel,
  sharedOnlyVerdict,
  planGroupId,
  sharedPlanName,
  sharingFor,
};
