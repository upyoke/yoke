// One flow definition, read-only: what it is for, its facts, its stages in
// order with what each one does, and its most recent runs. Definitions are
// created, versioned and disabled with `yoke deployment-flows`; a page that
// could rewrite one would be a second authority over an artifact runs
// already depend on, so this page has no controls for it.
import { el, statePill } from "./universe_view_support.js";
import {
  isPersonDecided,
  isQaStage,
  stageFactList,
  stageRunnerLabel,
} from "./universe_delivery_flow_stage_policy.js";

export const RECENT_RUNS_SHOWN = 5;

export function flowName(row) {
  return row.name || row.id || "Unnamed flow";
}
export function flowStatus(row) {
  return String(row.status || "unknown").toLowerCase();
}
function stagesFor(row) {
  return Array.isArray(row.stages) ? row.stages : [];
}
// Where a flow deploys is a typed fact, not an inference from an absence.
// `persistent` names a registered environment row; `ephemeral` deploys
// per-run preview substrate, which has no environment to name; no tier at
// all is a merge-only flow that deploys nowhere.
export function destinationLabel(row) {
  const environment = String(row?.target_environment || "").trim();
  if (environment) return environment;
  const tier = String(row?.target_tier || "").trim().toLowerCase();
  if (tier === "ephemeral") return "Ephemeral";
  // A persistent tier is declared to name an environment, so one that does
  // not is an incomplete definition rather than a flow without a target.
  if (tier === "persistent") return "Not set";
  return "No deploy target";
}

function fact(documentNode, label, value) {
  const node = el(documentNode, "div", "delivery-flow-fact");
  node.appendChild(el(documentNode, "dt", null, label));
  const dd = el(documentNode, "dd");
  if (typeof value === "string") dd.textContent = value;
  else dd.appendChild(value);
  node.appendChild(dd);
  return node;
}

function replacesFact(documentNode, row, options) {
  const replacedId = row.supersedes_flow_id;
  if (!replacedId) return null;
  const replaced = options.flows.find((flow) => String(flow.id) === String(replacedId));
  const link = el(documentNode, "a", "delivery-flow-replaces", replaced ? flowName(replaced) : String(replacedId));
  link.href = options.flowHref(replacedId);
  if (replaced) {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      options.onSelect(replaced);
    });
  }
  return fact(documentNode, "Replaces", link);
}

function renderPipeline(documentNode, row, actorNames) {
  const stages = stagesFor(row);
  const region = el(documentNode, "section", "delivery-flow-pipeline-region");
  region.appendChild(el(documentNode, "h4", "delivery-flow-section-title", "Pipeline"));
  if (!stages.length) {
    region.appendChild(el(
      documentNode, "p", "delivery-flow-no-stages", "No stages are published for this flow.",
    ));
    return region;
  }
  const pipeline = el(documentNode, "ol", "delivery-flow-pipeline");
  for (const [index, stage] of stages.entries()) {
    const item = el(documentNode, "li", "delivery-flow-stage");
    if (isPersonDecided(stage)) item.classList.add("is-person");
    else if (isQaStage(stage)) item.classList.add("is-qa");
    item.appendChild(el(documentNode, "span", "delivery-flow-stage-num", String(index + 1)));
    const body = el(documentNode, "div", "delivery-flow-stage-body");
    const head = el(documentNode, "div", "delivery-flow-stage-head");
    head.appendChild(el(documentNode, "strong", "delivery-flow-stage-name", stage.name));
    const runner = stageRunnerLabel(stage, stages);
    if (runner) head.appendChild(el(documentNode, "span", "delivery-flow-stage-kind", runner));
    if (isPersonDecided(stage)) {
      head.appendChild(el(documentNode, "span", "delivery-flow-stage-person", "a person decides"));
    }
    body.appendChild(head);
    const facts = stageFactList(documentNode, stage, actorNames);
    if (facts) body.appendChild(facts);
    item.appendChild(body);
    pipeline.appendChild(item);
  }
  region.appendChild(pipeline);
  return region;
}

function runWhen(row) {
  const stamp = row.completed_at || row.started_at || row.created_at;
  return stamp ? `${String(stamp).replace("T", " ").slice(0, 16)} UTC` : "";
}

// The flow's latest runs, read after the detail paints so the definition
// never waits on run history.
function renderRecentRuns(documentNode, detail, row, options) {
  const region = el(documentNode, "section", "delivery-flow-runs-region");
  detail.appendChild(region);
  if (!options.loadRecentRuns) return;
  options.loadRecentRuns(row).then((runs) => {
    if (!runs?.length || region.parentNode !== detail) return;
    region.appendChild(el(documentNode, "h4", "delivery-flow-section-title", "Recent runs"));
    const list = el(documentNode, "ul", "delivery-flow-runs");
    for (const run of runs.slice(0, RECENT_RUNS_SHOWN)) {
      const item = el(documentNode, "li");
      const link = el(documentNode, "a", "mono delivery-flow-run-link", String(run.id));
      link.href = options.runHref(run);
      item.appendChild(link);
      const pill = statePill(documentNode, run.status, run.status);
      if (pill) item.appendChild(pill);
      item.appendChild(el(documentNode, "span", "delivery-flow-run-when", runWhen(run)));
      list.appendChild(item);
    }
    region.appendChild(list);
  });
}

export function renderDeliveryFlowDetail(documentNode, detail, row, options = {}) {
  detail.replaceChildren();
  const back = el(documentNode, "button", "delivery-flow-back", "‹ All flows");
  back.type = "button";
  back.addEventListener("click", () => options.onBack?.());
  detail.appendChild(back);
  if (!row) {
    detail.classList.add("is-empty");
    detail.removeAttribute("aria-labelledby");
    detail.appendChild(el(documentNode, "p", "delivery-flow-detail-empty", "Choose a flow."));
    return;
  }
  detail.classList.remove("is-empty");
  const header = el(documentNode, "header", "delivery-flow-detail-header");
  const heading = el(documentNode, "h3");
  heading.appendChild(el(documentNode, "span", "delivery-flow-detail-name", flowName(row)));
  heading.setAttribute("id", "delivery-flow-detail-heading");
  if (flowStatus(row) !== "active") {
    const pill = statePill(documentNode, flowStatus(row), flowStatus(row));
    if (pill) {
      heading.appendChild(documentNode.createTextNode(" "));
      heading.appendChild(pill);
    }
  }
  header.appendChild(heading);
  header.appendChild(el(documentNode, "p", "mono delivery-flow-id", row.id || "identity unavailable"));
  detail.appendChild(header);
  detail.setAttribute("aria-labelledby", "delivery-flow-detail-heading");
  if (row.description) {
    detail.appendChild(el(documentNode, "p", "delivery-flow-description", row.description));
  }
  const facts = el(documentNode, "dl", "delivery-flow-facts");
  facts.appendChild(fact(documentNode, "Project", row.project || "—"));
  facts.appendChild(fact(documentNode, "Environment", destinationLabel(row)));
  facts.appendChild(fact(documentNode, "Target tier", row.target_tier || "—"));
  facts.appendChild(fact(documentNode, "On failure", row.on_failure || "halt"));
  const replaces = replacesFact(documentNode, row, {
    flows: options.flows || [],
    flowHref: options.flowHref || (() => "#"),
    onSelect: options.onSelect || (() => {}),
  });
  if (replaces) facts.appendChild(replaces);
  detail.appendChild(facts);
  detail.appendChild(renderPipeline(documentNode, row, options.actorNames || {}));
  renderRecentRuns(documentNode, detail, row, options);
}
