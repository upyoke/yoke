import { el } from "./universe_view_support.js";
import {
  appendWorkflowDialogFooter,
  workflowDialogShell,
} from "./workflow_dialog_shell.js";
import {
  COORDINATION_LEVELS,
  coordinationLevel,
} from "./workflow_view_policy.js";

const LEVEL_COPY = {
  none: {
    tag: "fastest",
    description:
      "Skip the path survey and path claims. Work still runs in its normal " +
      "lane, without a preflight overlap check or reserved files.",
  },
  survey: {
    tag: "faster",
    description:
      "Record the expected touch set, check active work and declared paths, " +
      "and reserve nothing.",
  },
  claims: {
    tag: "safest",
    description:
      "Register and reserve the files the item will touch; registration " +
      "already detects overlapping work.",
  },
};

function enabledAxes(policies) {
  return {
    claims: ["required", "required_per_task"].includes(policies.path_claims),
    survey: (policies.path_survey ?? "required") === "required",
  };
}

function targetAxes(level) {
  return {
    claims: level === "claims",
    survey: level === "survey",
  };
}

function orderedEdits(policies, targetLevel) {
  const current = enabledAxes(policies);
  const target = targetAxes(targetLevel);
  const edits = [];
  for (const axis of ["claims", "survey"]) {
    if (current[axis] && !target[axis]) edits.push([axis, false]);
  }
  for (const axis of ["survey", "claims"]) {
    if (!current[axis] && target[axis]) edits.push([axis, true]);
  }
  return edits;
}

export function renderCoordinationDialog(
  documentNode,
  host,
  workflow,
  close,
  mutation,
  load,
) {
  const title = "Preventing overlapping work";
  const shell = workflowDialogShell(documentNode, host, title, close);
  shell.dialog.appendChild(el(
    documentNode,
    "p",
    "workflow-dialog-subtitle",
    "Choose the default for new " + (workflow.name || workflow.id) + " items.",
  ));
  const choices = el(documentNode, "div", "workflow-coordination-choices");
  choices.setAttribute("role", "radiogroup");
  choices.setAttribute("aria-label", title);
  const publishedPolicies = {
    ...(workflow.definition?.policies || {}),
  };
  let selected = coordinationLevel(publishedPolicies);
  const controls = new Map();
  const select = (levelId) => {
    selected = levelId;
    for (const [id, control] of controls) {
      const active = id === selected;
      control.setAttribute("aria-checked", String(active));
      control.classList.toggle("selected", active);
    }
  };
  for (const level of COORDINATION_LEVELS) {
    const copy = LEVEL_COPY[level.id];
    const control = el(
      documentNode, "button", "workflow-coordination-option",
    );
    control.type = "button";
    control.setAttribute("role", "radio");
    control.appendChild(el(
      documentNode, "strong", "workflow-coordination-name", level.label,
    ));
    control.appendChild(el(
      documentNode, "span", "workflow-coordination-tag", copy.tag,
    ));
    control.appendChild(el(
      documentNode, "span", "workflow-coordination-description",
      copy.description,
    ));
    control.addEventListener("click", () => select(level.id));
    controls.set(level.id, control);
    choices.appendChild(control);
  }
  select(selected);
  shell.dialog.appendChild(choices);

  let expectedVersion = Number(workflow.current_version);
  appendWorkflowDialogFooter(documentNode, shell.dialog, {
    impact:
      "Changing this default publishes immutable workflow versions. Items " +
      "already underway stay pinned to v" + workflow.current_version + ".",
    confirmText: "Save coordination default",
    dismiss: shell.dismiss,
    activate: shell.activate,
    save: async () => {
      for (const [axis, enabled] of orderedEdits(
        publishedPolicies, selected,
      )) {
        const result = await mutation("workflows.policy_defaults.publish", {
          workflow_id: workflow.id,
          expected_current_version: expectedVersion,
          ["path_" + axis + "_default"]: enabled,
        });
        expectedVersion = Number(result.version || expectedVersion + 1);
        publishedPolicies["path_" + axis] = enabled ? "required" : "optional";
      }
      close();
      await load();
    },
  });
}
