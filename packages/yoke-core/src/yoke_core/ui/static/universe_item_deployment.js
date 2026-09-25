// The delivery box every Frontier card carries: where this item is going,
// and where it has already landed.
//
// One component draws it for every band that shows delivery — an item
// waiting to ship and one already finished are the same question asked at
// two moments, so they get the same box rather than two renderings that
// drift apart.
//
// Membership is who owes the item a delivery. Candidate containment can also
// show a landing while it is being delivered, without calling it membership.
// The overview projection removes a merely contained landing after its first
// successful delivery to that environment. Run history keeps every run.
// Never guess from matching projects or nearby timestamps. The time shown is
// the run's completion, the moment the deployment finished, rather than when
// the item was merged or when the run row was last touched.
//
// A run still moving says so in the present tense. Only a succeeded run is
// allowed to say the item was deployed, and an item whose carrying run never
// recorded a completion says the time is unavailable instead of borrowing one.

import { deploymentRunHref } from "./universe_navigation.js";
import { NO_ENVIRONMENT_LABEL } from "./deployment_environment_copy.js";
import { navIcon } from "./universe_nav_sidebar.js";
import { relativeAgePhrase } from "./universe_time.js";
import { el, statePill } from "./universe_view_support.js";

const SUCCEEDED = "succeeded";
const FAILED = "failed";
const TERMINAL_RUN_STATES = new Set([SUCCEEDED, FAILED, "cancelled"]);
const STALLED_AFTER_MS = 30 * 60 * 1000;

function runItems(run) {
  const members = (run.member_items || []).map((item) => ({ item, relation: "member" }));
  const candidates = Object.hasOwn(run, "delivery_candidate_items")
    ? run.delivery_candidate_items
    : !TERMINAL_RUN_STATES.has(String(run.status || ""))
      ? run.contained_items || []
      : run.carried_work?.items || [];
  const memberIds = new Set(members.map(({ item }) => memberItemId(item)));
  return members.concat((candidates || [])
    .filter((item) => !memberIds.has(memberItemId(item)))
    .map((item) => ({ item, relation: "candidate" })));
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
    for (const { item, relation } of runItems(run)) {
      const itemId = memberItemId(item);
      if (!itemId) continue;
      if (!index.has(itemId)) index.set(itemId, []);
      index.get(itemId).push({ ...run, delivery_relation: relation });
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

//: A run still moving. Anything else has recorded its outcome.
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
 * One live run per environment, plus the newest meaningful terminal run per
 * environment. Concurrent stage and prod deploys are two release lines, so
 * one global live slot would hide the older of the two. Older succeeded
 * runs to the same environment are superseded by definition, as is a failure
 * that a later success replaced. A latest failure stays visible until then.
 */
export function shownDeliveryRuns(carried) {
  const shown = [];
  const environmentsSeen = new Set();
  const liveEnvironmentsSeen = new Set();
  for (const run of newestFirst(carried)) {
    const status = String(run.status || "");
    const environment = runEnvironment(run);
    if (!TERMINAL_RUN_STATES.has(status)) {
      if (liveEnvironmentsSeen.has(environment)) continue;
      liveEnvironmentsSeen.add(environment);
      shown.push(run);
      continue;
    }
    if (status !== SUCCEEDED && status !== FAILED) continue;
    if (environmentsSeen.has(environment)) continue;
    environmentsSeen.add(environment);
    shown.push(run);
  }
  return shown;
}

/**
 * What the card says about the merges it can account for.
 *
 * The count is of merge commits this item has a surviving RECORD of — the
 * queue batch blocks and the merge receipt the projection reads — and the
 * word says so. That is narrower than how many times the branch landed: the
 * receipt is one settled entry per branch, so a branch that landed four times
 * leaves one. The card names the landings themselves from `item_landings`,
 * and a box calling its narrower number "merges" beside that put two
 * contradicting counts of one thing on one card.
 *
 * A merge that landed after the last run is still one of these, and saying so
 * is the point of the line. One is "1 recorded merge" — a card that said
 * "1 recorded merges" at a reader undid the care the rest of the box takes.
 */
export function mergesPhrase(delivery) {
  const merges = Number(delivery?.merges || 0);
  if (!merges) return "no recorded merge";
  const deployed = Number(delivery?.deployed || 0);
  const notDeployed = Number(delivery?.not_deployed ?? merges - deployed);
  const noun = merges === 1 ? "recorded merge" : "recorded merges";
  return `${merges} ${noun} · ${deployed} deployed · ${notDeployed} not deployed`;
}

/**
 * Which flow the box names as shipping this item.
 *
 * The overview row's effective completion flow when the serving build
 * resolved one: the item's stored pin, else the project default (labeled
 * as inherited), else the flow of a release that carried a merge. "no flow"
 * is only the last case — an item that stores none, whose project declares
 * none, and whose merges no release has carried. An unreadable default is
 * named as unread, never as "no flow".
 *
 * A row that lacks the new fields is an older serving build: draw the
 * stored-flow label this box already used, rather than refusing the
 * roster. Blanking every Frontier card for one mixed-version window would
 * hide the board; the previous label is wrong for unpinned defaults but
 * still names a flow when the item stored one.
 */
function hasCompletionFlowFields(row) {
  return Object.prototype.hasOwnProperty.call(row, "completion_flow")
    && Object.prototype.hasOwnProperty.call(row, "completion_flow_source");
}

function namedFlowId(row) {
  if (hasCompletionFlowFields(row)) {
    return String(row.completion_flow || "") || String(row.delivery?.flow || "");
  }
  return String(row.deployment_flow || "") || String(row.delivery?.flow || "");
}

export function deliveryFlowLabel(row) {
  if (hasCompletionFlowFields(row)) {
    if (String(row.completion_flow_source || "") === "unreadable") {
      return "its project default could not be read";
    }
    const resolved = String(row.completion_flow || "");
    if (resolved) {
      return String(row.completion_flow_source || "") === "project_default"
        ? `${resolved} (project default)`
        : resolved;
    }
    return String(row.delivery?.flow || "") || "no flow";
  }
  const stored = String(row.deployment_flow || "");
  if (stored) return stored;
  return String(row.delivery?.flow || "") || "no flow";
}

/**
 * One run's sub-card: the truck, what the run is doing, and when.
 *
 * `row` is the item the card belongs to, which supplies both the project the
 * run link is scoped by and the flow a differing run flow is measured
 * against.
 */
function deliveryRunCard(documentNode, run, row) {
  const status = String(run.status || "unknown");
  const card = el(documentNode, "a", "item-deployment");
  const icon = navIcon(documentNode, "shipping");
  icon.classList.add("item-deployment-icon");
  card.appendChild(icon);
  // A run may ship a bound project's candidate, so scope its link to the
  // run's project rather than the item's project.
  card.href = deploymentRunHref(
    run.project_id ?? row.project_id ?? null, run.id || run.run_id,
  );
  const pill = statePill(documentNode, status, status);
  if (pill) card.appendChild(pill);
  card.appendChild(el(
    documentNode,
    "strong",
    "item-deployment-environment",
    runEnvironment(run) || NO_ENVIRONMENT_LABEL,
  ));
  card.appendChild(runTiming(documentNode, run, status));
  // The flow only when it is not the item's own: repeating the line above on
  // every sub-card says nothing, while a differing flow is the whole point.
  const flow = String(run.flow || "");
  if (flow && flow !== namedFlowId(row)) {
    card.appendChild(el(
      documentNode, "small", "item-deployment-flow", flow,
    ));
  }
  card.appendChild(el(
    documentNode, "small", "item-deployment-run", String(run.id || run.run_id || ""),
  ));
  card.appendChild(el(
    documentNode, "small", "item-deployment-relation",
    run.delivery_relation === "member" ? "run member" : "candidate contains landing",
  ));
  return card;
}

// When the run did the thing the card claims. A finished deployment is past
// tense from its completion; a run still moving is present tense from when it
// started, because "Deployed" about a run that has not landed is a lie the
// state chip beside it would contradict.
function runTiming(documentNode, run, status) {
  const completed = String(run.completed_at || "");
  if (TERMINAL_RUN_STATES.has(status)) {
    const action = status === SUCCEEDED
      ? "Deployed"
      : `${status.charAt(0).toUpperCase()}${status.slice(1)}`;
    if (!completed) {
      return el(
        documentNode,
        "span",
        "item-deployment-time is-unavailable",
        `${action.toLowerCase()} time unavailable`,
      );
    }
    return timeNode(documentNode, completed, `${action} ${relativeAgePhrase(completed)}`);
  }
  const started = String(run.started_at || run.created_at || "");
  if (!started) {
    return el(documentNode, "span", "item-deployment-time", "Deploying now");
  }
  const startedAt = Date.parse(started);
  if (Number.isFinite(startedAt) && Date.now() - startedAt > STALLED_AFTER_MS) {
    return timeNode(
      documentNode, started, `Deployment delayed · started ${relativeAgePhrase(started)}`,
    );
  }
  return timeNode(
    documentNode, started, `Deploying since ${relativeAgePhrase(started)}`,
  );
}

function timeNode(documentNode, stamp, text) {
  const when = el(documentNode, "time", "item-deployment-time", text);
  when.setAttribute("datetime", stamp);
  return when;
}

// No run has picked the item up. The truck is still the subject of the box,
// drawn muted rather than absent, so the empty state reads as the same thing
// in an earlier moment instead of as a different kind of card.
function noRunYet(documentNode) {
  const row = el(documentNode, "div", "item-delivery-empty");
  const icon = navIcon(documentNode, "shipping");
  icon.classList.add("item-deployment-icon");
  icon.classList.add("is-muted");
  row.appendChild(icon);
  row.appendChild(el(documentNode, "span", null, "Not in a run yet"));
  return row;
}

/**
 * Append the delivery box for `row` to its card.
 *
 * Drawn for every card that shows delivery, whether or not a run has picked
 * the item up: "merged, in no run yet" is a state a reader is waiting on, and
 * an absent box would read as nothing to say rather than as nothing yet done.
 * `deployments` is the index built above.
 */
export function appendItemDelivery(documentNode, card, row, deployments) {
  const box = el(documentNode, "div", "item-delivery");
  const head = el(documentNode, "div", "item-delivery-head");
  head.appendChild(el(
    documentNode,
    "span",
    "item-delivery-flow",
    deliveryFlowLabel(row),
  ));
  head.appendChild(el(
    documentNode, "span", "item-delivery-merges", mergesPhrase(row.delivery),
  ));
  box.appendChild(head);
  const itemId = row.internal_id ?? row.item_id ?? row.id;
  const carried = deployments?.get(String(itemId)) || [];
  const runs = shownDeliveryRuns(carried);
  if (!runs.length) {
    box.appendChild(noRunYet(documentNode));
  } else {
    for (const run of runs) {
      box.appendChild(deliveryRunCard(documentNode, run, row));
    }
  }
  card.appendChild(box);
  return box;
}
