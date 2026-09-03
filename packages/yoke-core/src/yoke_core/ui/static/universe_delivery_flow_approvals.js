import { callFunction, el, statePill } from "./universe_view_support.js";
import { ROLE_LABELS } from "./workflow_mechanics_data.js";
import { openApprovalEditor } from "./workflow_mechanics_dialogs.js";
import { button } from "./workflow_view_primitives.js";

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

function unwrapResult(callResult, fallback) {
  if (callResult.status === 200 && callResult.envelope?.success) {
    return callResult.envelope.result || {};
  }
  throw new Error(
    callResult.envelope?.error?.message || fallback,
  );
}

async function loadApprovers(client) {
  try {
    const result = unwrapResult(
      await callFunction(client, "workflows.mechanics.get", {}),
      "Could not load named approvers.",
    );
    return result.approvers || [];
  } catch {
    return [];
  }
}

function applyApprovalGates(stages, gates) {
  return stages.map((stage) => {
    if (stage.step_runner !== "human-approval") return stage;
    const gate = gates[stage.name] || { roles: [], actors: [], mode: "any" };
    return {
      ...stage,
      approvals: {
        roles: [...gate.roles],
        actors: [...gate.actors],
        mode: gate.mode === "all" ? "all" : "any",
      },
    };
  });
}

async function saveFlowApprovals(client, flowId, gates) {
  const read = unwrapResult(
    await callFunction(
      client, "deployment_flows.stages", { flow_id: flowId },
    ),
    "Could not read flow stages.",
  );
  let stages = read.stages;
  if (typeof stages === "string") stages = JSON.parse(stages);
  if (!Array.isArray(stages)) {
    throw new Error("Flow stages are not a JSON array.");
  }
  unwrapResult(
    await callFunction(client, "deployment_flows.update_stages", {
      flow_id: flowId,
      stages: JSON.stringify(applyApprovalGates(stages, gates)),
    }),
    "Could not save stage approvals.",
  );
}

export function openDeliveryFlowApprovalEditor({
  documentNode, host, row, client, reload,
}) {
  const stages = Array.isArray(row.approval_stages) ? row.approval_stages : [];
  if (!stages.length || !client || !host) return;
  const close = () => { host.replaceChildren(); };
  const source = Object.fromEntries(stages.map((stage) => [
    stage.name,
    {
      roles: [...(stage.approvals?.roles || [])],
      actors: [...(stage.approvals?.actors || [])].map(Number),
      mode: stage.approvals?.mode === "all" ? "all" : "any",
    },
  ]));
  loadApprovers(client).then((approvers) => {
    openApprovalEditor({
      documentNode,
      host,
      data: { approvers },
      close,
      subjects: stages.map((stage) => ({ id: stage.name, label: stage.name })),
      source,
      title: `Stage approvals — ${flowName(row)}`,
      subjectLabel: "Stage",
      impact:
        "Saving updates who may approve this flow's human-approval stages. " +
        "Runs already in flight keep the snapshot they started with.",
      requireEverySubject: true,
      confirmText: "Save stage approvals",
      save: async (gates) => {
        await saveFlowApprovals(client, row.id, gates);
        close();
        if (reload) await reload();
      },
    });
  });
}

export function renderDeliveryFlowDetail(
  documentNode, detail, row, options = {},
) {
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
  const approvalStages = Array.isArray(row.approval_stages)
    ? row.approval_stages : [];
  if (approvalStages.length && options.client && options.host) {
    const edit = button(
      documentNode,
      "Edit who may approve",
      "workflow-button delivery-flow-edit-approvals",
    );
    edit.addEventListener("click", () => {
      openDeliveryFlowApprovalEditor({
        documentNode,
        host: options.host,
        row,
        client: options.client,
        reload: options.reload,
      });
    });
    header.appendChild(edit);
  }
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
