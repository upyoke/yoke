// One flow definition, read-only: its metadata and the ordered pipeline a run
// freezes when it references the flow. A definition is authored and versioned
// by command, and a page that could rewrite one would be a second authority
// over an artifact runs already depend on.
import { el, statePill } from "./universe_view_support.js";
import {
  stageKindLabel,
  stagePolicyList,
} from "./universe_delivery_flow_stage_policy.js";

function flowName(row) {
  return row.name || row.id || "Unnamed flow";
}
function flowStatus(row) {
  return String(row.status || "unknown").toLowerCase();
}
function stagesFor(row) {
  return Array.isArray(row.stages) ? row.stages : [];
}
// Where a flow deploys is a typed fact, not an inference from an absence.
// `persistent` names a registered environment row; `ephemeral` deploys
// per-run preview substrate, which has no environment to name; no tier at
// all is a merge-only flow that deploys nowhere. Reading a missing
// environment as a preview told every merge-only flow it shipped to a
// destination it does not have.
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

function metadataFact(documentNode, label, value) {
  const fact = el(documentNode, "div", "delivery-flow-fact");
  fact.appendChild(el(documentNode, "dt", null, label));
  fact.appendChild(el(documentNode, "dd", null, value || "Not set"));
  return fact;
}

function renderPipeline(documentNode, row) {
  const stages = stagesFor(row);
  const region = el(documentNode, "section", "delivery-flow-pipeline-region");
  region.appendChild(el(documentNode, "h4", null, "Pipeline"));
  if (!stages.length) {
    region.appendChild(el(
      documentNode,
      "p",
      "delivery-flow-no-stages",
      "No stages are published for this flow.",
    ));
    return region;
  }
  const pipeline = el(documentNode, "ol", "delivery-flow-pipeline");
  pipeline.setAttribute(
    "aria-label",
    `Flow stages: ${stages.map((stage) => stage.name).join(", ")}`,
  );
  for (const [index, stage] of stages.entries()) {
    const item = el(documentNode, "li", "delivery-flow-stage");
    if (stage.stage_kind === "qa") item.classList.add("is-qa");
    if (stage.approvals || stage.verdict) item.classList.add("is-approval");
    const head = el(documentNode, "div", "delivery-flow-stage-head");
    head.appendChild(el(
      documentNode,
      "span",
      "delivery-flow-stage-index",
      String(index + 1).padStart(2, "0"),
    ));
    const kind = stageKindLabel(stage);
    if (kind) {
      head.appendChild(el(documentNode, "span", "delivery-flow-stage-kind", kind));
    }
    item.appendChild(head);
    item.appendChild(el(
      documentNode,
      "span",
      "delivery-flow-stage-name",
      stage.name,
    ));
    const policy = stagePolicyList(documentNode, stage);
    if (policy) item.appendChild(policy);
    pipeline.appendChild(item);
  }
  region.appendChild(pipeline);
  return region;
}

export function renderDeliveryFlowDetail(documentNode, detail, row) {
  detail.replaceChildren();
  if (!row) {
    detail.classList.add("is-empty");
    detail.removeAttribute("aria-labelledby");
    detail.appendChild(el(
      documentNode,
      "p",
      "delivery-flow-detail-empty",
      "Choose a visible flow to inspect its pipeline.",
    ));
    return;
  }
  detail.classList.remove("is-empty");
  const header = el(documentNode, "header", "delivery-flow-detail-header");
  header.appendChild(el(
    documentNode, "p", "delivery-flow-eyebrow", "Selected flow",
  ));
  const titleRow = el(documentNode, "div", "delivery-flow-detail-title");
  const heading = el(documentNode, "h3", null, flowName(row));
  heading.setAttribute("id", "delivery-flow-detail-heading");
  titleRow.appendChild(heading);
  const pill = statePill(documentNode, flowStatus(row), flowStatus(row));
  if (pill) titleRow.appendChild(pill);
  header.appendChild(titleRow);
  header.appendChild(el(
    documentNode,
    "code",
    "delivery-flow-id",
    row.id || "identity unavailable",
  ));
  detail.appendChild(header);
  detail.setAttribute("aria-labelledby", "delivery-flow-detail-heading");

  const facts = el(documentNode, "dl", "delivery-flow-facts");
  facts.appendChild(metadataFact(documentNode, "Project", row.project));
  facts.appendChild(metadataFact(
    documentNode, "Environment", destinationLabel(row),
  ));
  facts.appendChild(metadataFact(
    documentNode, "Target tier", row.target_tier || "No deploy target",
  ));
  facts.appendChild(metadataFact(
    documentNode, "On failure", row.on_failure || "halt",
  ));
  facts.appendChild(metadataFact(
    documentNode,
    "Stage count",
    `${stagesFor(row).length} stage${stagesFor(row).length === 1 ? "" : "s"}`,
  ));
  detail.appendChild(facts);
  detail.appendChild(renderPipeline(documentNode, row));
}
