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
import { NO_ENVIRONMENT_LABEL } from "./deployment_environment_copy.js";
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
 * Newest completion first. Selected-flow filtering belongs to the
 * card painter: an ancillary Stage success must not become "Deployed".
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
      String(right.completed_at || "").localeCompare(
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
    run.target_environment || run.target_tier || NO_ENVIRONMENT_LABEL,
  ));
  const completed = String(run.completed_at || "");
  if (status === SUCCEEDED && completed) {
    const when = el(documentNode, "time", "item-deployment-time");
    when.setAttribute("datetime", completed);
    when.textContent = `Deployed ${relativeAgePhrase(completed)}`;
    card.appendChild(when);
  } else if (status === SUCCEEDED) {
    card.appendChild(el(
      documentNode,
      "span",
      "item-deployment-time is-unavailable",
      "deployment time unavailable",
    ));
  }
  // A run that has not succeeded says so through its own state chip and run
  // id; a sentence repeating the chip read as a defect rather than a status.
  card.appendChild(el(
    documentNode, "small", "item-deployment-run", String(run.id || run.run_id || ""),
  ));
  return card;
}

//: A run still moving. Anything else has recorded its outcome.
const TERMINAL_RUN_STATES = new Set([SUCCEEDED, "failed", "cancelled"]);

function runEnvironment(run) {
  return String(run.target_environment || run.target_tier || "");
}

function newestFirst(runs) {
  // Created, not completed: a live run has no completion yet and would sort
  // to the bottom on one, which is the opposite of what "newest" means here.
  return [...runs].sort((left, right) => String(
    right.created_at || "",
  ).localeCompare(String(left.created_at || "")));
}

/**
 * The runs worth drawing: what is shipping now, and where it last landed.
 *
 * One live run, plus the newest succeeded run per environment. Older
 * succeeded runs to the same environment are superseded by definition, and
 * failed ones a later success replaced are history the run page still holds.
 */
export function shownDeliveryRuns(carried) {
  const shown = [];
  const environmentsSeen = new Set();
  let liveShown = false;
  for (const run of newestFirst(carried)) {
    const status = String(run.status || "");
    if (!TERMINAL_RUN_STATES.has(status)) {
      if (liveShown) continue;
      liveShown = true;
      shown.push(run);
      continue;
    }
    if (status !== SUCCEEDED) continue;
    const environment = runEnvironment(run);
    if (environmentsSeen.has(environment)) continue;
    environmentsSeen.add(environment);
    shown.push(run);
  }
  return shown;
}

/**
 * What the card says about this item's landed merges.
 *
 * The counts come from the projection, which reads the item's own recorded
 * landings: a merge that landed after the last run is still one of them, and
 * saying so is the point of the line.
 */
export function mergesPhrase(delivery) {
  const merges = Number(delivery?.merges || 0);
  if (!merges) return "no merges";
  const deployed = Number(delivery?.deployed || 0);
  const notDeployed = Number(delivery?.not_deployed ?? merges - deployed);
  return `${merges} merges · ${deployed} deployed · ${notDeployed} not deployed`;
}

function deliveryRunCard(documentNode, run, row) {
  const status = String(run.status || "unknown");
  const card = el(documentNode, "a", "release-delivery-run");
  card.href = deploymentRunHref(row.project_id ?? null, run.id || run.run_id);
  card.appendChild(el(
    documentNode,
    "small",
    "release-delivery-run-id",
    String(run.id || run.run_id || ""),
  ));
  card.appendChild(el(
    documentNode,
    "strong",
    "release-delivery-run-environment",
    runEnvironment(run) || NO_ENVIRONMENT_LABEL,
  ));
  const pill = statePill(documentNode, status, status);
  if (pill) card.appendChild(pill);
  // The flow only when it is not the item's own: repeating the line above
  // every sub-card says nothing, while a differing flow is the whole point.
  const flow = String(run.flow || "");
  if (flow && flow !== String(row.deployment_flow || "")) {
    card.appendChild(el(
      documentNode, "small", "release-delivery-run-flow", flow,
    ));
  }
  return card;
}

/**
 * Append the delivery box a Release-band card always carries.
 *
 * Unlike the Done band's box, this one is drawn even when no run has picked
 * the item up: "waiting to ship, in no run yet" is the state the band exists
 * to show, and an absent box would read as nothing to say.
 */
export function appendReleaseDelivery(documentNode, card, row, deployments) {
  const box = el(documentNode, "div", "release-delivery");
  box.appendChild(el(
    documentNode,
    "span",
    "release-delivery-flow",
    String(row.deployment_flow || "") || "no flow",
  ));
  box.appendChild(el(
    documentNode, "span", "release-delivery-merges", mergesPhrase(row.delivery),
  ));
  const itemId = row.internal_id ?? row.item_id ?? row.id;
  const carried = deployments?.get(String(itemId)) || [];
  const runs = shownDeliveryRuns(carried);
  if (!runs.length) {
    box.appendChild(el(
      documentNode, "p", "release-delivery-empty", "Not in a run yet",
    ));
  } else {
    for (const run of runs) {
      box.appendChild(deliveryRunCard(documentNode, run, row));
    }
  }
  card.appendChild(box);
  return box;
}


/**
 * Append the selected-flow deployment that carried `row`, when one did.
 *
 * `deployments` is the index built above. An item no selected-flow run
 * carries gets nothing — silence is correct there, because an ancillary
 * Stage success is participation, not this item's release.
 */
export function appendItemDeployment(documentNode, card, row, deployments) {
  if (!deployments) return null;
  const itemId = row.internal_id ?? row.item_id ?? row.id;
  const carried = deployments.get(String(itemId)) || [];
  if (!carried.length) return null;
  const selectedFlow = String(row.deployment_flow || "");
  const matching = selectedFlow
    ? carried.filter((run) => String(run.flow || "") === selectedFlow)
    : [];
  if (!matching.length) return null;
  matching.sort((left, right) => (
    Number(String(right.status || "") === SUCCEEDED)
    - Number(String(left.status || "") === SUCCEEDED)
    || String(right.completed_at || "").localeCompare(
      String(left.completed_at || ""),
    )
  ));
  const node = deploymentCard(documentNode, matching[0], row.project_id);
  card.appendChild(node);
  return node;
}
