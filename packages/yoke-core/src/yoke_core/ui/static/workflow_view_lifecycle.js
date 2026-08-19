import {
  el,
} from "./universe_view_support.js";
import {
  button,
  setWorkflowInlineContent,
  workflowPanel,
  workflowStageDisplayLabel,
} from "./workflow_view_primitives.js";
import { gateDescription } from "./workflow_view_gate_copy.js";
import { relativeAge } from "./universe_time.js";

const ENTRY_SURFACE_COPY = {
  dash: {
    web_form: {
      title: "Enter a Dash on the web",
      route: "#/items/new",
      routeLabel: "open →",
    },
    cli: {
      title: "CLI",
      command: 'yoke dash "<title>" "<instruction>"',
    },
    harness_skill: {
      title: "Harness",
      command: '/yoke dash "<instruction>"',
      note: "agent authors title and files for you",
      noteBreak: true,
    },
    promotion: {
      title: "Promote from field note",
      description: [
        "In ",
        { kind: "code", text: "/yoke curate" },
        ", a triaged observation becomes a filed Dash — " +
          "the note keeps a link to it.",
      ],
    },
  },
  issue: {
    harness_skill: {
      title: "Filed in a harness",
      command: "/yoke idea",
      note: "the interview produces the refined fields an Issue needs",
    },
    promotion: {
      title: "Escalated from a Dash",
      description:
        "the dash records findings, files the Issue, and cancels itself " +
        "with a link",
    },
  },
  epic: {
    harness_skill: {
      title: "Filed in a harness",
      command: "/yoke idea",
      note:
        "interview; decomposition into tasks belongs to the Architect at planning",
    },
  },
  blitz: {
    harness_skill: {
      title: "Filed in a harness",
      command: "/yoke idea",
      note:
        "links the single execution strategy document the Blitz will run",
    },
  },
};

const DEFAULT_ENTRY_SURFACE_COPY = {
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
    const descriptionNode = el(
      documentNode, "div", "workflow-detail-row-description",
    );
    setWorkflowInlineContent(documentNode, descriptionNode, description);
    content.appendChild(descriptionNode);
  }
  row.appendChild(content);
  if (identifier) {
    row.appendChild(el(
      documentNode, "code", "workflow-detail-id", identifier,
    ));
  }
  return { row, content };
}

function entrySurfaceRows(documentNode, workflow, host) {
  for (const surfaceId of workflow.definition?.entry_surfaces || []) {
    const copy = ENTRY_SURFACE_COPY[workflow.id]?.[surfaceId] ||
      DEFAULT_ENTRY_SURFACE_COPY[surfaceId] || {
      title: surfaceId,
      description: "",
    };
    const rendered = detailRow(
      documentNode, copy.title, copy.description, null,
    );
    if (copy.command) {
      const entryCopy = el(
        documentNode, "div", "workflow-entry-copy",
      );
      entryCopy.appendChild(el(
        documentNode, "code", "workflow-entry-command", copy.command,
      ));
      if (copy.note) {
        entryCopy.appendChild(el(
          documentNode,
          "span",
          `workflow-entry-note${copy.noteBreak ? " block" : ""}`,
          copy.note,
        ));
      }
      rendered.content.appendChild(entryCopy);
    }
    if (copy.route) {
      const link = el(
        documentNode,
        "a",
        "workflow-entry-link",
        copy.routeLabel || "open →",
      );
      link.href = copy.route;
      rendered.row.appendChild(link);
    }
    host.appendChild(rendered.row);
  }
}

function gateRows(documentNode, workflow, gates, catalogById, host) {
  for (const gateRef of gates) {
    const gate = catalogById.get(gateRef.id) || {
      id: gateRef.id,
      name: gateRef.id,
      description: "",
      source_kind: "",
    };
    const gateTitle = gateRef.mode
      ? `${gate.name} — ${gateRef.mode}` : gate.name;
    const description = gateDescription(workflow, gate);
    const rendered = detailRow(
      documentNode, gateTitle, description, gate.id,
    );
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
  const stages = workflow.definition?.stages || [];
  const initial = stages[0] && stages[0].id === stage.id;
  const stageLabel = workflowStageDisplayLabel(workflow, stage);
  const title = el(
    documentNode,
    "div",
    `workflow-stage-detail-heading${initial ? " initial" : ""}`,
  );
  title.appendChild(el(
    documentNode, "strong", "workflow-stage-detail-label", stageLabel,
  ));
  const gates = stage.gates || [];
  if (!initial && !gates.length && !stage.description) {
    titleRow.classList.add("empty");
  }
  title.appendChild(el(
    documentNode,
    "span",
    "workflow-stage-detail-count",
    initial
      ? `Entry surfaces for ${/^[aeiou]/i.test(stageLabel) ? "an" : "a"} ` +
        stageLabel
      : gates.length
        ? `• ${gates.length} ${gates.length === 1 ? "check" : "checks"} on entry`
        : "• no checks on entry",
  ));
  titleRow.appendChild(title);
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
    gateRows(documentNode, workflow, gates, catalogById, rows);
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
  workflow,
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
    documentNode,
    "span",
    "workflow-stage-label",
    workflowStageDisplayLabel(workflow, stage),
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
    inlineVersion: true,
    status: workflow.status,
    detail: workflow.published_at
      ? `published ${relativeAge(workflow.published_at)}` : "",
  });
  const flow = el(documentNode, "div", "workflow-lifecycle");
  stages.forEach((stage, index) => {
    flow.appendChild(stageButton(
      documentNode,
      workflow,
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
