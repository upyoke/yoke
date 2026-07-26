import {
  el,
  statePill,
} from "./universe_view_support.js";
import {
  button,
  formatTimestamp,
  workflowPanel,
} from "./workflow_view_primitives.js";

const ENTRY_SURFACE_COPY = {
  web_form: {
    title: "Web form",
    description: "File this workflow directly from the Items screen.",
  },
  cli: {
    title: "CLI",
    description: "File this workflow with its registered yoke command.",
  },
  harness_skill: {
    title: "Harness",
    description: "File this workflow through its registered harness skill.",
  },
  promotion: {
    title: "Promotion",
    description: "Promote an existing Yoke record into this workflow.",
  },
};

function detailRow(documentNode, title, description, identifier) {
  const row = el(documentNode, "div", "workflow-detail-row");
  const content = el(documentNode, "div", "workflow-detail-content");
  content.appendChild(el(
    documentNode, "div", "workflow-detail-row-title", title,
  ));
  if (description) {
    content.appendChild(el(
      documentNode,
      "div",
      "workflow-detail-row-description",
      description,
    ));
  }
  row.appendChild(content);
  row.appendChild(el(
    documentNode, "code", "workflow-detail-id", identifier,
  ));
  return { row, content };
}

function entrySurfaceRows(documentNode, workflow, host) {
  for (const surfaceId of workflow.definition?.entry_surfaces || []) {
    const copy = ENTRY_SURFACE_COPY[surfaceId] || {
      title: surfaceId,
      description: "",
    };
    host.appendChild(detailRow(
      documentNode, copy.title, copy.description, surfaceId,
    ).row);
  }
}

function gateRows(documentNode, gates, catalogById, host) {
  for (const gateRef of gates) {
    const gate = catalogById.get(gateRef.id) || {
      id: gateRef.id,
      name: gateRef.id,
      description: "",
      source_kind: "",
    };
    const gateTitle = gateRef.mode
      ? `${gate.name} — ${gateRef.mode}` : gate.name;
    const rendered = detailRow(
      documentNode, gateTitle, gate.description, gate.id,
    );
    const heading = rendered.content.children[0];
    const source = statePill(documentNode, gate.source_kind);
    if (source) heading.appendChild(source);
    if (gate.id === "qa_verification") {
      const link = el(documentNode, "a", "workflow-home-link", "QA →");
      link.href = "#/qa";
      rendered.row.appendChild(link);
    }
    host.appendChild(rendered.row);
  }
}

function stageDetail(documentNode, workflow, stage, catalogById) {
  const detail = el(documentNode, "div", "workflow-stage-detail");
  const titleRow = el(documentNode, "div", "workflow-stage-detail-title");
  const title = el(documentNode, "div");
  title.appendChild(el(
    documentNode, "strong", null, stage.label || stage.id,
  ));
  title.appendChild(el(
    documentNode, "span", "workflow-stage-id", stage.id,
  ));
  titleRow.appendChild(title);

  const stages = workflow.definition?.stages || [];
  const initial = stages[0] && stages[0].id === stage.id;
  const gates = stage.gates || [];
  titleRow.appendChild(el(
    documentNode,
    "span",
    "workflow-stage-detail-count",
    initial
      ? `Entry surfaces for ${stage.label || stage.id}`
      : `${gates.length} ${gates.length === 1 ? "check" : "checks"} on entry`,
  ));
  detail.appendChild(titleRow);

  if (stage.description) {
    detail.appendChild(el(
      documentNode, "p", "workflow-stage-description", stage.description,
    ));
  }

  const rows = el(documentNode, "div", "workflow-detail-stack");
  if (initial) {
    entrySurfaceRows(documentNode, workflow, rows);
  } else if (gates.length) {
    gateRows(documentNode, gates, catalogById, rows);
  } else {
    rows.appendChild(el(
      documentNode,
      "p",
      "empty workflow-no-checks",
      "Nothing is checked on entry.",
    ));
  }
  detail.appendChild(rows);
  return detail;
}

function stageButton(
  documentNode,
  stage,
  index,
  selected,
  selectStage,
) {
  const control = button(
    documentNode,
    "",
    `workflow-stage${selected ? " selected" : ""}`,
  );
  control.setAttribute("aria-pressed", String(selected));
  control.appendChild(el(
    documentNode, "span", "workflow-stage-label", stage.label || stage.id,
  ));
  const gateCount = (stage.gates || []).length;
  if (gateCount) {
    control.appendChild(el(
      documentNode,
      "span",
      "workflow-stage-count",
      `${gateCount} ${gateCount === 1 ? "check" : "checks"}`,
    ));
  } else if (index === 0) {
    control.appendChild(el(
      documentNode, "span", "workflow-stage-count", "entry",
    ));
  }
  control.addEventListener("click", () => selectStage(stage.id));
  return control;
}

export function renderStages(
  documentNode,
  workflow,
  catalogById,
  selectedStageId,
  selectStage,
) {
  const stages = workflow.definition?.stages || [];
  const { panel, body } = workflowPanel(documentNode, "Stages", {
    count: stages.length,
    version: workflow.current_version,
    detail: workflow.published_at
      ? `published ${formatTimestamp(workflow.published_at)}` : "",
  });
  const flow = el(documentNode, "div", "workflow-lifecycle");
  stages.forEach((stage, index) => {
    flow.appendChild(stageButton(
      documentNode,
      stage,
      index,
      stage.id === selectedStageId,
      selectStage,
    ));
    if (index < stages.length - 1) {
      flow.appendChild(el(documentNode, "span", "workflow-stage-arrow", "→"));
    }
  });
  body.appendChild(flow);
  const selected = stages.find((stage) => stage.id === selectedStageId) ||
    stages[0];
  if (selected) {
    body.appendChild(stageDetail(
      documentNode, workflow, selected, catalogById,
    ));
  }
  return panel;
}
