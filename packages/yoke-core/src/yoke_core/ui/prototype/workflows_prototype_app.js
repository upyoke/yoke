// Composes the prototype workflows page: tabs, stages, the uniform policy
// grid, mechanics, inline execution instructions, and the redesigned version
// history. State lives in this module; nothing is persisted and no call goes
// out, so every interaction is safe to click.

import { button, el, panel } from "./workflows_prototype_dom.js";
import {
  PROTOTYPE_INSTRUCTIONS,
  PROTOTYPE_PROJECTS,
  PROTOTYPE_WORKFLOWS,
} from "./workflows_prototype_fixture.js";
import { renderPolicyGrid } from "./workflows_prototype_policy_grid.js";
import { renderInstructions } from "./workflows_prototype_instructions.js";
import { renderVersions } from "./workflows_prototype_versions.js";

const GATE_NAMES = {
  conflict_survey: "Conflict survey",
  work_claim_activation: "Work-claim activation",
  qa_verification: "QA requirements",
  dash_evidence: "Dash evidence",
  path_claim_boundary: "Path-claim boundary",
  architecture_impact: "Architecture impact",
  db_claim_prose: "DB claim consistency",
  db_mutation: "Governed DB mutation",
  plan_simulation: "Plan simulation",
};

const SKILL_LINE = {
  dash: "Run /yoke dash in a supported harness — it runs the whole item.",
  blitz: "Run /yoke refine, then /yoke blitz — the document is executed directly.",
  issue: "Run /yoke refine, advance, polish, usher.",
  epic: "Run /yoke refine, shepherd, conduct, polish, usher.",
};

const state = {
  workflowId: "dash",
  stageByWorkflow: new Map(),
  instructions: structuredClone(PROTOTYPE_INSTRUCTIONS),
  editingInstruction: null,
  workflows: structuredClone(PROTOTYPE_WORKFLOWS),
  notice: null,
  nextInstructionId: 100,
};

function selected() {
  return state.workflows.find((entry) => entry.id === state.workflowId);
}

function renderTabs(documentNode, host) {
  host.replaceChildren();
  for (const workflow of state.workflows) {
    const tab = button(documentNode, workflow.name,
      `workflow-tab${workflow.id === state.workflowId ? " selected" : ""}`);
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(workflow.id === state.workflowId));
    const canon = workflow.canon_status?.state;
    if (canon === "update_available" || canon === "customized_update_available") {
      tab.appendChild(el(documentNode, "span", "workflow-tab-status update",
        "update"));
    }
    tab.addEventListener("click", () => {
      state.workflowId = workflow.id;
      state.editingInstruction = null;
      render(documentNode);
    });
    host.appendChild(tab);
  }
}

function renderStages(documentNode, workflow) {
  const { panel: host, body } = panel(documentNode, "Stages",
    { meta: `current · v${workflow.current_version}` });
  const stages = workflow.definition.stages;
  const selectedId = state.stageByWorkflow.get(workflow.id) || stages[0].id;
  const lifecycle = el(documentNode, "div", "workflow-lifecycle");
  for (const [index, stage] of stages.entries()) {
    if (index) {
      lifecycle.appendChild(el(documentNode, "span", "workflow-stage-arrow", "→"));
    }
    const node = button(documentNode, "",
      `workflow-stage${stage.id === selectedId ? " selected" : ""}`);
    node.appendChild(el(documentNode, "span", "workflow-stage-label", stage.id));
    node.appendChild(el(documentNode, "span", "workflow-stage-count",
      stage.gates.length
        ? `${stage.gates.length} check${stage.gates.length === 1 ? "" : "s"}`
        : "—"));
    node.addEventListener("click", () => {
      state.stageByWorkflow.set(workflow.id, stage.id);
      render(documentNode);
    });
    lifecycle.appendChild(node);
  }
  body.appendChild(lifecycle);
  const stage = stages.find((entry) => entry.id === selectedId);
  const detail = el(documentNode, "div", "workflow-stage-detail");
  detail.appendChild(el(documentNode, "div", "workflow-stage-detail-label",
    stage.id));
  if (!stage.gates.length) {
    detail.appendChild(el(documentNode, "p", "workflow-no-checks",
      "Nothing is checked on entry."));
  }
  for (const gate of stage.gates) {
    detail.appendChild(el(documentNode, "p", "workflow-stage-description",
      GATE_NAMES[gate.id] || gate.id));
  }
  body.appendChild(detail);
  return host;
}

function renderPolicies(documentNode, workflow) {
  const { panel: host, body } = panel(documentNode, "Execution posture",
    { meta: `current · v${workflow.current_version}` });
  body.appendChild(el(documentNode, "p", "wp-panel-note",
    "Every policy this workflow carries, in one order, for every workflow. " +
    "Nothing is hidden because of its value — off is a state worth reading, " +
    "and a lock means something enforces it."));
  renderPolicyGrid(
    documentNode, body, workflow, workflow.definition.policies,
    (row) => notify(documentNode,
      `Prototype: editing “${row.label}” would publish ${workflow.name} v${
        workflow.current_version + 1}.`),
  );
  return host;
}

function renderMechanics(documentNode, workflow) {
  const { panel: host, body } = panel(documentNode, "Mechanics");
  const rows = el(documentNode, "div", "workflow-detail-stack");
  for (const [title, description] of [
    ["Skill", SKILL_LINE[workflow.id]],
    ["Testing", "Default test plan — set per project."],
    ["Approvals", "No approval gate on any transition."],
    ["Delivery", "Default deployment flow — set per project."],
  ]) {
    const row = el(documentNode, "div", "workflow-detail-row");
    const content = el(documentNode, "div", "workflow-detail-content");
    content.appendChild(el(documentNode, "div", "workflow-detail-row-title",
      title));
    content.appendChild(el(documentNode, "div",
      "workflow-detail-row-description", description));
    row.appendChild(content);
    rows.appendChild(row);
  }
  body.appendChild(rows);
  return host;
}

function notify(documentNode, message) {
  state.notice = message;
  render(documentNode);
}

function instructionContext(documentNode) {
  return {
    instructions: state.instructions,
    workflows: state.workflows,
    projects: PROTOTYPE_PROJECTS,
    editing: state.editingInstruction,
    edit: (instruction) => {
      state.editingInstruction = instruction;
      render(documentNode);
    },
    cancel: () => {
      state.editingInstruction = null;
      render(documentNode);
    },
    save: (edit) => {
      if (edit.id == null) {
        state.instructions.push({ ...edit, id: state.nextInstructionId += 1 });
      } else {
        const index = state.instructions
          .findIndex((entry) => entry.id === edit.id);
        state.instructions[index] = { ...state.instructions[index], ...edit };
      }
      state.editingInstruction = null;
      notify(documentNode, "Prototype: instruction saved in this page only.");
    },
    remove: () => {
      state.instructions = state.instructions
        .filter((entry) => entry.id !== state.editingInstruction.id);
      state.editingInstruction = null;
      notify(documentNode, "Prototype: instruction removed in this page only.");
    },
  };
}

function versionActions(documentNode) {
  return {
    setFollow: (workflow, mode) => {
      workflow.canon_follow = mode;
      notify(documentNode, `Prototype: ${workflow.name} now follows Yoke ${
        mode === "auto" ? "automatically" : "manually"}.`);
    },
    takeAll: (workflow) => notify(documentNode,
      `Prototype: this would merge every pending Yoke version into ${
        workflow.name} and publish the result.`),
    makeCurrent: (workflow, version) => {
      workflow.current_version = version.version;
      notify(documentNode,
        `Prototype: new ${workflow.name} items would pin v${version.version}; ` +
        "items already underway do not move.");
    },
  };
}

export function render(documentNode) {
  const root = documentNode.getElementById("prototype-root");
  const workflow = selected();
  const tabs = el(documentNode, "div", "workflow-tabs");
  tabs.setAttribute("role", "tablist");
  renderTabs(documentNode, tabs);
  const stack = el(documentNode, "div", "workflow-stack");
  stack.appendChild(renderStages(documentNode, workflow));
  stack.appendChild(renderPolicies(documentNode, workflow));
  stack.appendChild(renderMechanics(documentNode, workflow));
  stack.appendChild(renderInstructions(
    documentNode, workflow, instructionContext(documentNode),
  ));
  stack.appendChild(renderVersions(
    documentNode, workflow, versionActions(documentNode),
  ));
  const children = [tabs, el(documentNode, "p", "workflow-intro",
    workflow.description)];
  if (state.notice) {
    const notice = el(documentNode, "div", "wp-notice", state.notice);
    notice.setAttribute("role", "status");
    children.push(notice);
  }
  children.push(stack);
  root.replaceChildren(...children);
  state.notice = null;
}
