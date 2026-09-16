// Who may approve a flow's human-approval stages is read here and configured
// by command: a flow definition is authored and versioned outside the
// dashboard, and a page that could rewrite one would be a second authority
// over an artifact a run freezes.
import { el, statePill } from "./universe_view_support.js";
import { ROLE_LABELS } from "./workflow_mechanics_data.js";

function flowName(row) {
  return row.name || row.id || "Unnamed flow";
}
function flowStatus(row) {
  return String(row.status || "unknown").toLowerCase();
}
function stagesFor(row) {
  return Array.isArray(row.stage_names) ? row.stage_names : [];
}
function approvalByName(row) {
  const entries = Array.isArray(row.approval_stages) ? row.approval_stages : [];
  return new Map(entries.map((stage) => [stage.name, stage]));
}
function whoMayApprove(approvals) {
  const who = [
    ...(approvals?.roles || []).map((role) => ROLE_LABELS[role] || role),
    ...(approvals?.actors || []).map((actorId) => `actor ${actorId}`),
  ];
  if (!who.length) return "No one configured";
  return who.join(approvals?.mode === "all" ? " and " : " or ");
}
function metadataFact(documentNode, label, value) {
  const fact = el(documentNode, "div", "delivery-flow-fact");
  fact.appendChild(el(documentNode, "dt", null, label));
  fact.appendChild(el(documentNode, "dd", null, value || "Not set"));
  return fact;
}

function renderPipeline(documentNode, row) {
  const stages = stagesFor(row);
  const addressed = approvalByName(row);
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
  pipeline.setAttribute("aria-label", `Flow stages: ${stages.join(", ")}`);
  for (const [index, stage] of stages.entries()) {
    const item = el(documentNode, "li", "delivery-flow-stage");
    const addressedStage = addressed.get(stage);
    if (addressedStage) item.classList.add("is-approval");
    item.appendChild(el(
      documentNode,
      "span",
      "delivery-flow-stage-index",
      String(index + 1).padStart(2, "0"),
    ));
    item.appendChild(el(
      documentNode,
      "span",
      "delivery-flow-stage-name",
      stage,
    ));
    if (addressedStage) {
      item.appendChild(el(
        documentNode,
        "span",
        "delivery-flow-stage-approvers",
        whoMayApprove(addressedStage.approvals),
      ));
    }
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
    documentNode, "Environment", row.target_environment || "Ephemeral",
  ));
  facts.appendChild(metadataFact(documentNode, "Target tier", row.target_tier));
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
