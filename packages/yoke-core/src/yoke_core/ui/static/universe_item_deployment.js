// Where a finished item actually went.
//
// Membership is the recorded carried work of a deployment run — the run's own
// member rows joined on the item's internal id — never a guess from matching
// projects or nearby timestamps. The time shown is the run's completion, the
// moment the deployment finished, rather than when the item was merged or
// when the run row was last touched.
//
// A run that failed, was cancelled, or is still executing is reported as what
// it is. Only a succeeded run is allowed to say the item was deployed, and an
// item whose carrying run never recorded a completion says the time is
// unavailable instead of borrowing one.

import { deploymentRunHref } from "./universe_navigation.js";
import { navIcon } from "./universe_nav_sidebar.js";
import { relativeAgePhrase } from "./universe_time.js";
import { el, statePill } from "./universe_view_support.js";

const SUCCEEDED = "succeeded";

function runMembers(run) {
  if ((run.member_items || []).length) return run.member_items;
  return run.carried_work?.items || [];
}

function memberItemId(member) {
  const value = member.id ?? member.item_id;
  return value === undefined || value === null ? null : String(value);
}

/**
 * Index runs by the internal id of each item they carry.
 *
 * Runs arrive newest-completion-first within each item's list, and a
 * succeeded run outranks any other outcome: a release that landed is what
 * "where did this go" means, and a later failed retry does not undo it.
 */
export function deploymentsByItemId(runs) {
  const index = new Map();
  for (const run of runs || []) {
    for (const member of runMembers(run)) {
      const itemId = memberItemId(member);
      if (!itemId) continue;
      if (!index.has(itemId)) index.set(itemId, []);
      index.get(itemId).push(run);
    }
  }
  for (const [, carried] of index) {
    carried.sort((left, right) => (
      Number(String(right.status || "") === SUCCEEDED)
      - Number(String(left.status || "") === SUCCEEDED)
      || String(right.completed_at || "").localeCompare(
        String(left.completed_at || ""),
      )
    ));
  }
  return index;
}

function deploymentCard(documentNode, run, projectId) {
  const status = String(run.status || "unknown");
  const card = el(documentNode, "a", "item-deployment");
  const icon = navIcon(documentNode, "shipping");
  icon.classList.add("item-deployment-icon");
  card.appendChild(icon);
  // The run and the item it carries are the same project by membership,
  // so the item's own project scopes the link.
  card.href = deploymentRunHref(projectId ?? null, run.id || run.run_id);
  const pill = statePill(documentNode, status, status);
  if (pill) card.appendChild(pill);
  card.appendChild(el(
    documentNode,
    "strong",
    "item-deployment-environment",
    run.target_environment || run.target_tier || "environment unavailable",
  ));
  const completed = String(run.completed_at || "");
  if (status === SUCCEEDED && completed) {
    const when = el(documentNode, "time", "item-deployment-time");
    when.setAttribute("datetime", completed);
    when.textContent = `Deployed ${relativeAgePhrase(completed)}`;
    card.appendChild(when);
  } else {
    card.appendChild(el(
      documentNode,
      "span",
      "item-deployment-time is-unavailable",
      status === SUCCEEDED
        ? "deployment time unavailable"
        : `carried by a run that ${status}`,
    ));
  }
  card.appendChild(el(
    documentNode, "small", "item-deployment-run", String(run.id || run.run_id || ""),
  ));
  return card;
}

/**
 * Append the deployment that carried `row`, when one did.
 *
 * `deployments` is the index built above. An item no run carries gets nothing
 * — silence is correct there, because plenty of finished work ships with the
 * next release rather than one of its own.
 */
export function appendItemDeployment(documentNode, card, row, deployments) {
  if (!deployments) return null;
  const itemId = row.internal_id ?? row.item_id ?? row.id;
  const carried = deployments.get(String(itemId)) || [];
  if (!carried.length) return null;
  const node = deploymentCard(documentNode, carried[0], row.project_id);
  card.appendChild(node);
  return node;
}
