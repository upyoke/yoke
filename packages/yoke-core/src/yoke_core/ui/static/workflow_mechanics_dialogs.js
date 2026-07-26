import { el } from "./universe_view_support.js";
import { button } from "./workflow_view_primitives.js";
import {
  optionsForProject,
  projectKey,
  ROLE_LABELS,
  selectedProjectDefault,
} from "./workflow_mechanics_data.js";

const ROLE_OPTIONS = [
  ["owner", "Project owner"],
  ["operator", "Project operator"],
  ["admin", "Org admin"],
];

function fieldLabel(documentNode, text) {
  return el(documentNode, "div", "workflow-field-label", text);
}

function option(documentNode, value, label, selected) {
  const node = el(documentNode, "option", null, label);
  node.value = String(value);
  node.selected = String(value) === String(selected);
  return node;
}

function checkbox(documentNode, checked, label, toggle) {
  const row = el(documentNode, "label", "workflow-checkbox");
  const input = el(documentNode, "input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", toggle);
  row.appendChild(input);
  row.appendChild(el(documentNode, "span", null, label));
  return row;
}

function dialogShell(documentNode, host, title, close) {
  host.replaceChildren();
  const backdrop = el(documentNode, "div", "workflow-dialog-backdrop");
  const dialog = el(
    documentNode, "section",
    "workflow-dialog workflow-mechanics-dialog",
  );
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.appendChild(el(
    documentNode, "h2", "workflow-dialog-title", title,
  ));
  backdrop.appendChild(dialog);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) close();
  });
  host.appendChild(backdrop);
  return dialog;
}

function footer(documentNode, dialog, {
  impact = "", confirmText, close, save, disabled = false,
}) {
  const error = el(documentNode, "p", "workflow-dialog-error");
  error.hidden = true;
  dialog.appendChild(error);
  const row = el(documentNode, "div", "workflow-dialog-footer");
  if (impact) {
    row.appendChild(el(
      documentNode, "p", "workflow-dialog-impact", impact,
    ));
  }
  const actions = el(documentNode, "div", "workflow-dialog-actions");
  const cancel = button(documentNode, "Cancel");
  const confirm = button(
    documentNode, confirmText, "workflow-button primary",
  );
  confirm.disabled = disabled;
  cancel.addEventListener("click", close);
  confirm.addEventListener("click", async () => {
    cancel.disabled = true;
    confirm.disabled = true;
    confirm.textContent = "Saving…";
    error.hidden = true;
    try {
      await save();
    } catch (failure) {
      cancel.disabled = false;
      confirm.disabled = disabled;
      confirm.textContent = confirmText;
      error.textContent = String(failure?.message || failure);
      error.hidden = false;
    }
  });
  actions.appendChild(cancel);
  actions.appendChild(confirm);
  row.appendChild(actions);
  dialog.appendChild(row);
}

function transitionIds(workflow) {
  const stages = workflow.definition?.stages || [];
  const declared = new Set(
    (workflow.definition?.transitions || []).map(
      (transition) => transition.to_stage_id,
    ),
  );
  const ids = stages.map((stage) => stage.id).filter((id) => declared.has(id));
  return ids.length ? ids : stages.slice(1).map((stage) => stage.id);
}

export function openApprovalEditor({
  documentNode, host, workflow, data, close, save,
}) {
  const ids = transitionIds(workflow);
  const source = workflow.definition?.policies?.approval_defaults || {};
  const gates = Object.fromEntries(ids.map((transitionId) => {
    const gate = source[transitionId] || {};
    return [transitionId, {
      roles: [...(gate.roles || [])],
      actors: [...(gate.actors || [])].map(Number),
    }];
  }));
  const state = { transitionId: ids[0], gates };

  const render = () => {
    const name = workflow.name || workflow.id;
    const dialog = dialogShell(
      documentNode, host, `Default approvals — ${name}`, close,
    );
    dialog.appendChild(fieldLabel(documentNode, "Transition"));
    const transition = el(documentNode, "select", "workflow-field");
    for (const transitionId of ids) {
      const configured = (
        gates[transitionId].roles.length || gates[transitionId].actors.length
      );
      transition.appendChild(option(
        documentNode,
        transitionId,
        `${transitionId}${configured ? " ✓" : ""}`,
        state.transitionId,
      ));
    }
    transition.value = state.transitionId;
    transition.addEventListener("change", (event) => {
      state.transitionId = event.target.value;
      render();
    });
    dialog.appendChild(transition);
    const gate = gates[state.transitionId];
    dialog.appendChild(el(
      documentNode,
      "p",
      "workflow-field-help",
      `Anyone who matches may approve ${state.transitionId}`,
    ));
    for (const [role, label] of ROLE_OPTIONS) {
      dialog.appendChild(checkbox(
        documentNode,
        gate.roles.includes(role),
        label,
        () => {
          gate.roles = gate.roles.includes(role)
            ? gate.roles.filter((value) => value !== role)
            : [...gate.roles, role];
          render();
        },
      ));
    }
    dialog.appendChild(fieldLabel(documentNode, "Or any of these people"));
    for (const actor of data.approvers) {
      dialog.appendChild(checkbox(
        documentNode,
        gate.actors.includes(Number(actor.id)),
        actor.label,
        () => {
          const actorId = Number(actor.id);
          gate.actors = gate.actors.includes(actorId)
            ? gate.actors.filter((value) => value !== actorId)
            : [...gate.actors, actorId];
          render();
        },
      ));
    }
    if (!data.approvers.length) {
      dialog.appendChild(el(
        documentNode, "p", "workflow-field-help",
        "No named human actors are available.",
      ));
    }
    const configured = ids.filter(
      (id) => gates[id].roles.length || gates[id].actors.length,
    );
    dialog.appendChild(el(
      documentNode,
      "p",
      "workflow-configured-summary",
      configured.length
        ? `Gates set: ${configured.join(" · ")}`
        : "No gates yet — a transition with no one selected has no approval.",
    ));
    footer(documentNode, dialog, {
      impact:
        `Saving creates a new version of the ${name} workflow. Items already ` +
        `underway stay pinned to v${workflow.current_version} and are unaffected.`,
      confirmText: "Save universe default",
      close,
      save: () => save(Object.fromEntries(
        Object.entries(gates).filter(
          ([, value]) => value.roles.length || value.actors.length,
        ),
      )),
    });
  };
  render();
}

export function openProjectDefaultEditor({
  documentNode, host, kind, workflow, projects, data, close, save,
}) {
  const available = projects.filter(
    (project) => optionsForProject(data, kind, project).length,
  );
  const state = {
    project: available[0] || projects[0],
    value: "",
    applyToAll: false,
  };
  const noun = kind === "testing" ? "test plan" : "deployment flow";
  const setProject = (project) => {
    state.project = project;
    const selected = selectedProjectDefault(
      data, kind, project, workflow.id,
    );
    const options = optionsForProject(data, kind, project);
    state.value = selected || (options[0] && String(options[0].id)) || "";
  };
  if (state.project) setProject(state.project);

  const render = () => {
    const name = workflow.name || workflow.id;
    const dialog = dialogShell(
      documentNode, host, `Default ${noun} — ${name}`, close,
    );
    dialog.appendChild(fieldLabel(documentNode, "Project"));
    const projectSelect = el(documentNode, "select", "workflow-field");
    for (const project of projects) {
      projectSelect.appendChild(option(
        documentNode,
        projectKey(project),
        projectKey(project),
        state.project && projectKey(state.project),
      ));
    }
    projectSelect.value = state.project ? projectKey(state.project) : "";
    projectSelect.addEventListener("change", (event) => {
      const project = projects.find(
        (row) => projectKey(row) === event.target.value,
      );
      if (project) setProject(project);
      render();
    });
    dialog.appendChild(projectSelect);
    const projectName = state.project ? projectKey(state.project) : "";
    dialog.appendChild(fieldLabel(
      documentNode,
      `Default ${noun} for ${name} in ${projectName}`,
    ));
    const choices = state.project
      ? optionsForProject(data, kind, state.project) : [];
    if (choices.length) {
      const valueSelect = el(documentNode, "select", "workflow-field");
      for (const choice of choices) {
        const value = String(choice.id);
        valueSelect.appendChild(option(
          documentNode, value, choice.slug || choice.name || value, state.value,
        ));
      }
      valueSelect.value = state.value;
      valueSelect.addEventListener("change", (event) => {
        state.value = event.target.value;
      });
      dialog.appendChild(valueSelect);
    } else {
      dialog.appendChild(el(
        documentNode, "p", "workflow-field-help",
        `${projectName || "This project"} has no ${noun}s yet.`,
      ));
    }
    if (state.project) {
      dialog.appendChild(checkbox(
        documentNode,
        state.applyToAll,
        `Apply to every workflow in ${projectName}`,
        () => {
          state.applyToAll = !state.applyToAll;
          render();
        },
      ));
    }
    footer(documentNode, dialog, {
      impact: "",
      confirmText: "Set default",
      close,
      disabled: !choices.length,
      save: () => save({
        project: projectName,
        value: state.value,
        applyToAll: state.applyToAll,
      }),
    });
  };
  render();
}
