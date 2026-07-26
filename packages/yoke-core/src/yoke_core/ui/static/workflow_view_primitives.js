import { el } from "./universe_view_support.js";

const BUILTIN_WORKFLOW_ORDER = ["dash", "blitz", "issue", "epic"];

const POLICY_VALUE_COPY = {
  ownership: {
    single_item_claim: "one active item claim",
    item_claim_and_task_lanes: "one epic claim + task lanes",
    session_item_and_document_claim:
      "session claims item; item claims its document",
    exclusive_session_work_claim:
      "exclusive work claim by harness session",
  },
  path_claims: {
    required: "required from file budget",
    required_per_task: "required per task budget",
    optional: "optional",
  },
  worktrees: {
    single_implementation_lane: "one implementation lane",
    worker_and_integration_lanes: "worker + integration lanes",
    worker_lanes_optional_integration:
      "worker lanes + optional integration",
  },
  parallelism: {
    inside_item: "inside the item only",
    task_graph: "task graph",
    maximum_safe_slices: "maximum safe slices",
    none: "none",
  },
  generated_children: {
    none: "never generated",
    epic_tasks: "epic tasks",
  },
};

export function button(
  documentNode,
  text,
  className = "workflow-button",
) {
  const node = el(documentNode, "button", className, text);
  node.type = "button";
  return node;
}

export function workflowPanel(documentNode, title, options = {}) {
  const panel = el(documentNode, "section", "panel workflow-panel");
  const header = el(documentNode, "div", "panel-header workflow-panel-header");
  const heading = el(documentNode, "h2", null, title);
  if (options.count !== undefined) {
    heading.appendChild(el(
      documentNode, "span", "panel-count", `· ${options.count}`,
    ));
  }
  if (options.inlineVersion && options.version !== undefined) {
    heading.appendChild(el(
      documentNode, "span", "workflow-version",
      `current · v${options.version}`,
    ));
  }
  header.appendChild(heading);
  const meta = el(documentNode, "div", "workflow-panel-meta");
  if (!options.inlineVersion && options.version !== undefined) {
    meta.appendChild(el(
      documentNode, "span", "workflow-version",
      `current · v${options.version}`,
    ));
  }
  if (options.detail) {
    meta.appendChild(el(
      documentNode, "span", "workflow-panel-detail", options.detail,
    ));
  }
  if (meta.children.length) header.appendChild(meta);
  panel.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  panel.appendChild(body);
  return { panel, body };
}

export function formatTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function sortedWorkflows(workflows) {
  const rank = new Map(
    BUILTIN_WORKFLOW_ORDER.map((workflowId, index) => [workflowId, index]),
  );
  return [...workflows].sort((left, right) => {
    const leftRank = rank.has(left.id)
      ? rank.get(left.id) : BUILTIN_WORKFLOW_ORDER.length;
    const rightRank = rank.has(right.id)
      ? rank.get(right.id) : BUILTIN_WORKFLOW_ORDER.length;
    return leftRank - rightRank ||
      String(left.name || left.id).localeCompare(String(right.name || right.id));
  });
}

export function readablePolicyValue(policy, value) {
  const declared = POLICY_VALUE_COPY[policy] || {};
  if (declared[value]) return declared[value];
  if (Array.isArray(value)) return value.join(" · ");
  return String(value ?? "").replaceAll("_", " ");
}

export function renderTabs(
  documentNode,
  host,
  workflows,
  selectedId,
  select,
) {
  host.replaceChildren();
  for (const workflow of workflows) {
    const tab = button(
      documentNode,
      workflow.name || workflow.id,
      `workflow-tab${workflow.id === selectedId ? " selected" : ""}`,
    );
    tab.setAttribute("aria-selected", String(workflow.id === selectedId));
    tab.addEventListener("click", () => select(workflow.id));
    host.appendChild(tab);
  }
}

export function renderWorkflowDialog(documentNode, host, spec) {
  host.replaceChildren();
  if (!spec) return;

  const backdrop = el(
    documentNode, "div", "workflow-dialog-backdrop",
  );
  const dialog = el(documentNode, "section", "workflow-dialog");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.appendChild(el(
    documentNode, "h2", "workflow-dialog-title", spec.title,
  ));
  if (spec.subtitle) {
    dialog.appendChild(el(
      documentNode, "p", "workflow-dialog-subtitle", spec.subtitle,
    ));
  }
  if (spec.lines && spec.lines.length) {
    const lines = el(documentNode, "div", "workflow-dialog-lines");
    for (const line of spec.lines) {
      const row = el(documentNode, "p", "workflow-dialog-line");
      row.appendChild(el(
        documentNode, "strong", null, line.title,
      ));
      row.appendChild(el(
        documentNode, "span", null, ` — ${line.description}`,
      ));
      lines.appendChild(row);
    }
    dialog.appendChild(lines);
  }
  const error = el(documentNode, "p", "workflow-dialog-error");
  error.hidden = true;
  dialog.appendChild(error);
  const footer = el(documentNode, "div", "workflow-dialog-footer");
  footer.appendChild(el(
    documentNode, "p", "workflow-dialog-impact", spec.impact,
  ));
  const actions = el(documentNode, "div", "workflow-dialog-actions");
  const cancel = button(documentNode, "Cancel", "workflow-button");
  const confirm = button(
    documentNode, spec.confirmText, "workflow-button primary",
  );
  cancel.addEventListener("click", spec.cancel);
  confirm.addEventListener("click", async () => {
    cancel.disabled = true;
    confirm.disabled = true;
    confirm.textContent = spec.pendingText || "Saving…";
    error.hidden = true;
    try {
      await spec.confirm();
    } catch (failure) {
      cancel.disabled = false;
      confirm.disabled = false;
      confirm.textContent = spec.confirmText;
      error.textContent = String(
        failure && failure.message ? failure.message : failure,
      );
      error.hidden = false;
    }
  });
  actions.appendChild(cancel);
  actions.appendChild(confirm);
  footer.appendChild(actions);
  dialog.appendChild(footer);
  backdrop.appendChild(dialog);
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) spec.cancel();
  });
  host.appendChild(backdrop);
}
