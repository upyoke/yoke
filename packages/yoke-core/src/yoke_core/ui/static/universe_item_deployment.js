// Delivery belongs to the item: each environment shows its own member QA
// or candidate containment, even while the carrying run waits on other work.
import { deploymentRunHref } from "./universe_navigation.js";
import { NO_ENVIRONMENT_LABEL } from "./deployment_environment_copy.js";
import { relativeAge, relativeAgePhrase } from "./universe_time.js";
import { el } from "./universe_view_support.js";

const TERMINAL_RUN_STATES = new Set(["succeeded", "failed", "cancelled"]);
const ACCEPTED_QA = new Set(["accepted", "discharged"]);

function memberItemId(member) {
  const value = member.public_ref ?? member.ref ?? member.item_ref;
  return value === undefined || value === null ? null : String(value);
}

function runItems(run) {
  const removed = (run.removed_member_items || []).map((item) => ({ item, relation: "removed" }));
  const removedIds = new Set(removed.map(({ item }) => memberItemId(item)));
  const members = (run.member_items || [])
    .filter((item) => !removedIds.has(memberItemId(item)))
    .map((item) => ({ item, relation: "member" }));
  const candidates = Object.hasOwn(run, "delivery_candidate_items")
    ? run.delivery_candidate_items
    : !TERMINAL_RUN_STATES.has(String(run.status || ""))
      ? run.contained_items || []
      : run.carried_work?.items || [];
  const memberIds = new Set(members.map(({ item }) => memberItemId(item)));
  return removed.concat(members, (candidates || [])
    .filter((item) => !memberIds.has(memberItemId(item)) && !removedIds.has(memberItemId(item)))
    .map((item) => ({ item, relation: "carried" })));
}

export function deploymentsByItemId(runs) {
  const index = new Map();
  for (const run of runs || []) {
    for (const { item, relation } of runItems(run)) {
      const itemId = memberItemId(item);
      if (!itemId) continue;
      if (!index.has(itemId)) index.set(itemId, []);
      index.get(itemId).push({
        ...run, delivery_relation: relation, delivery_item: item,
      });
    }
  }
  return index;
}

function runEnvironment(run) {
  return String(run.target_environment || run.target_tier || "");
}

// One current answer per environment. A newer attempt supersedes that
// environment's older success or failure, without hiding another environment.
export function shownDeliveryRuns(carried) {
  const seen = new Set();
  return [...carried].sort((left, right) => String(
    right.created_at || "",
  ).localeCompare(String(left.created_at || ""))).filter((run) => {
    const environment = runEnvironment(run);
    if (seen.has(environment)) return false;
    seen.add(environment);
    return true;
  });
}

// The flow id an item read's flow field names. Item reads project
// `deployment_flow` as `{value, source}`, and an older serving build returns
// the bare stored string, so the id is taken from either, never by
// stringifying the field.
export function flowId(field) {
  const value = field && typeof field === "object" ? field.value : field;
  return String(value ?? "").trim();
}

export function deliveryFlowLabel(row) {
  if (row.completion_flow_source === "unreadable") {
    return "its project default could not be read";
  }
  return flowId(row.completion_flow) || flowId(row.deployment_flow)
    || flowId(row.delivery?.flow) || "no flow";
}

function runStage(run) {
  return String(run.current_stage || run.stages?.find(
    (stage) => ["active", "failed", "stopped"].includes(stage.state),
  )?.name || "");
}

function itemOutcome(run) {
  if (run.delivery_relation === "removed") {
    const item = run.delivery_item;
    return {
      symbol: "○", text: "removed · QA cancelled · rides ",
      reason: item.reason, laterRunId: item.later_run_id,
      removed: true,
    };
  }
  const qa = run.delivery_item?.item_qa;
  if (qa?.failed_requirement_ids?.length) {
    return { symbol: "✗", text: `QA failed · ${qa.failed_requirement_ids.map((id) => `#${id}`).join(", ")}` };
  }
  if (qa?.state === "rejected") return { symbol: "✗", text: "QA failed" };
  if (run.delivery_relation === "member" && ACCEPTED_QA.has(qa?.state)) {
    return { symbol: "✓", text: `deployed · QA ${qa.state === "accepted" ? "passed" : "discharged"}`, finished: true };
  }
  const status = String(run.status || "");
  if (status === "failed" || status === "cancelled") {
    return { symbol: "✗", text: `${status === "failed" ? "deployment failed" : "deployment cancelled"}${runStage(run) ? ` · at ${runStage(run)}` : ""}`, reason: qa?.reason };
  }
  if (qa?.state === "unreadable") {
    return { symbol: "○", text: "QA unavailable", reason: qa.reason };
  }
  if (status === "succeeded") {
    return { symbol: "✓", text: run.delivery_relation === "member" ? "deployed" : "in build", finished: true };
  }
  const stage = runStage(run);
  const started = run.started_at || run.created_at;
  return {
    symbol: "◐",
    text: `deploying${stage ? ` · at ${stage}` : ""} · ${started ? relativeAge(started) : "time unavailable"}`,
  };
}

function runWait(run) {
  const ownId = memberItemId(run.delivery_item || {});
  const pending = (run.member_items || []).filter((member) => (
    memberItemId(member) !== ownId
    && (member.item_qa ? !ACCEPTED_QA.has(member.item_qa.state) : member.status !== "done")
  )).map((member) => member.ref).filter(Boolean);
  if (pending.length) return `run still open: waiting on ${pending.join(", ")}`;
  const gate = (run.gates || []).find((entry) => entry.status === "pending");
  const stage = gate?.subject_context?.stage || runStage(run);
  return `run still open: waiting ${gate ? "on approval" : "at"}${stage ? ` · ${stage}` : " · run completion"}`;
}

function environmentRow(documentNode, environment, outcome, run, row) {
  const card = el(documentNode, "div", "item-deployment");
  card.appendChild(el(documentNode, "strong", "item-deployment-environment", environment || NO_ENVIRONMENT_LABEL));
  const summary = el(documentNode, "span", "item-deployment-outcome", `${outcome.symbol} ${outcome.text}`);
  if (outcome.reason) summary.title = outcome.reason;
  if (outcome.removed) {
    if (outcome.laterRunId) {
      const later = el(documentNode, "a", "overview-card-link", outcome.laterRunId);
      later.href = deploymentRunHref(run.project_id ?? row.project_id ?? null, outcome.laterRunId);
      summary.appendChild(later);
    } else {
      summary.appendChild(documentNode.createTextNode("a later release"));
    }
  }
  card.appendChild(summary);
  if (run) {
    const link = el(documentNode, "a", "item-deployment-run", String(run.id || run.run_id || ""));
    link.href = deploymentRunHref(run.project_id ?? row.project_id ?? null, run.id || run.run_id);
    card.appendChild(link);
    card.appendChild(el(documentNode, "small", "item-deployment-relation", run.delivery_relation));
    if (outcome.finished && run.delivery_relation === "member"
        && !TERMINAL_RUN_STATES.has(String(run.status || ""))) {
      card.appendChild(el(documentNode, "small", "item-deployment-wait", runWait(run)));
    }
  } else {
    card.appendChild(el(documentNode, "span", "item-deployment-placeholder", "—"));
  }
  return card;
}

export function appendItemDelivery(documentNode, card, row, deployments, projects = []) {
  const box = el(documentNode, "div", "item-delivery");
  const head = el(documentNode, "div", "item-delivery-head");
  head.appendChild(el(documentNode, "span", "item-delivery-label", "Delivery"));
  head.appendChild(el(documentNode, "span", "item-card-delivery-flow", deliveryFlowLabel(row)));
  box.appendChild(head);
  if (row.merged_at) {
    const merged = el(documentNode, "small", "item-delivery-merged", `merged ${relativeAgePhrase(row.merged_at)}`);
    const number = row.merge_queue_pr_number;
    if (number) {
      merged.appendChild(documentNode.createTextNode(" · "));
      const repository = projects.find((project) => String(project.id) === String(row.project_id))?.github_repo;
      const pr = el(documentNode, repository ? "a" : "span", "item-delivery-pr", `PR ${number}`);
      if (repository) pr.href = `https://github.com/${repository}/pull/${number}`;
      merged.appendChild(pr);
    }
    box.appendChild(merged);
  } else if (row.delivery?.no_code_change) {
    // The item's own record says it shipped no code, so there is no merge to
    // wait for — an absent merge line alone would read as unfinished work.
    box.appendChild(el(documentNode, "small", "item-delivery-no-change", "no code change"));
  }
  const itemId = row.public_ref;
  const runs = shownDeliveryRuns(deployments?.get(String(itemId)) || []);
  for (const run of runs) {
    box.appendChild(environmentRow(documentNode, runEnvironment(run), itemOutcome(run), run, row));
  }
  const environment = String(row.completion_environment || "");
  // "Next release" is a promise only a flow can keep: an item that resolves
  // no completion flow has no release coming, so it shows no placeholder.
  const flow = flowId(row.completion_flow) || flowId(row.deployment_flow) || flowId(row.delivery?.flow);
  const awaiting = !runs.length || (environment && !runs.some((run) => runEnvironment(run) === environment));
  if (flow && awaiting) {
    box.appendChild(environmentRow(documentNode, environment, {
      symbol: "○", text: "not yet · next release",
    }, null, row));
  }
  card.appendChild(box);
  return box;
}

// Where an item's delivery stands, one environment per part, for a surface
// too compact for the delivery box: "stage ✓ · prod deploying".
export function deliverySummary(row, deployments) {
  const itemId = row.public_ref;
  const runs = shownDeliveryRuns(deployments?.get(String(itemId)) || [])
    .filter((run) => run.delivery_relation !== "removed");
  const parts = runs.map((run) => {
    const outcome = itemOutcome(run);
    const environment = runEnvironment(run) || NO_ENVIRONMENT_LABEL;
    if (outcome.finished) return `${environment} ✓`;
    if (outcome.symbol === "✗") return `${environment} ✗`;
    return `${environment} deploying`;
  });
  const environment = String(row.completion_environment || "");
  if (environment && !runs.some((run) => runEnvironment(run) === environment)) {
    parts.push(`${environment} not yet`);
  }
  return parts.join(" · ");
}
