import { el } from "./universe_view_support.js";
import {
  mountWorkflowDialog,
  workflowDomId,
} from "./workflow_accessibility.js";

const BUILTIN_WORKFLOW_ORDER = ["dash", "blitz", "issue", "epic", "task"];

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
    required: "required",
    required_per_task: "required per task",
    optional: "optional",
  },
  path_survey: {
    required: "on",
    optional: "off",
  },
  file_budget: {
    required: "required",
    required_per_task: "required per task",
    optional: "optional",
  },
  worktrees: {
    single_implementation_lane: "one implementation lane",
    worker_and_integration_lanes: "worker + integration lanes",
    worker_lanes_optional_integration:
      "worker lanes + optional integration",
    none: "no git lane",
  },
  generated_children: {
    none: "never generated",
    epic_tasks: "epic tasks",
  },
  delivery: {
    release_stage: "before done · waits in release until delivered",
    after_merge_action: "after done · closes on merge; delivery is separate",
    continuous_slice_actions: "during work · each slice proves delivery",
    merge_free: "no merge · done is the floor attestation",
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

export function setWorkflowInlineContent(documentNode, host, parts) {
  const values = Array.isArray(parts) ? parts : [parts];
  const text = values.map((part) => (
    typeof part === "string" ? part : String(part?.text || "")
  )).join("");
  host.textContent = text;
  if (typeof documentNode.createTextNode !== "function") return;

  const nodes = values.map((part) => {
    if (typeof part === "string") return documentNode.createTextNode(part);
    const kind = part?.kind === "strong" ? "strong" : "code";
    const className = [
      kind === "strong"
        ? "workflow-inline-strong" : "workflow-inline-code",
      part?.className || "",
    ].filter(Boolean).join(" ");
    return el(documentNode, kind, className, part?.text || "");
  });
  host.replaceChildren(...nodes);
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
  if (options.status && options.status !== "active") {
    heading.appendChild(el(
      documentNode,
      "span",
      `workflow-status ${options.status}`,
      options.status,
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

export function stageDisplayLabel(stage) {
  return String(stage?.label || stage?.id || "");
}

export function workflowStageDisplayLabel(workflow, stage) {
  if (BUILTIN_WORKFLOW_ORDER.includes(String(workflow?.id))) {
    return String(stage?.id || stage?.label || "");
  }
  return stageDisplayLabel(stage);
}

export function workflowStageLabel(workflow, stageId) {
  const stage = (workflow.definition?.stages || []).find(
    (candidate) => candidate.id === stageId,
  );
  return workflowStageDisplayLabel(workflow, stage) || String(stageId || "");
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
  const focusRenderedTab = (workflowId) => {
    const rendered = [...host.children].find(
      (node) => node.attributes?.get?.("data-workflow-id") === workflowId ||
        node.getAttribute?.("data-workflow-id") === workflowId,
    );
    if (typeof rendered?.focus === "function") rendered.focus();
  };
  for (const [index, workflow] of workflows.entries()) {
    const workflowName = workflow.name || workflow.id;
    const disabled = workflow.status === "disabled";
    const selected = workflow.id === selectedId;
    const tab = button(
      documentNode,
      workflowName,
      `workflow-tab${selected ? " selected" : ""}` +
        `${disabled ? " disabled" : ""}`,
    );
    if (disabled) {
      tab.appendChild(el(
        documentNode, "span", "workflow-tab-status", "disabled",
      ));
    }
    // Only the states worth crossing the list for. "Up to date" belongs on the
    // workflow you opened, not on every tab -- a row of reassurances is noise,
    // where a row of nothing-but-the-one-that-needs-you is a signal.
    const canonState = workflow.canon_status?.state;
    if (
      canonState === "update_available" ||
      canonState === "customized_update_available"
    ) {
      tab.appendChild(el(
        documentNode, "span", "workflow-tab-status update", "update",
      ));
    }
    tab.setAttribute(
      "aria-label",
      `${workflowName} workflow · ${disabled ? "disabled" : "active"}`,
    );
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(selected));
    tab.setAttribute("id", `workflow-tab-${workflowDomId(workflow.id)}`);
    tab.setAttribute(
      "aria-controls", `workflow-panel-${workflowDomId(workflow.id)}`,
    );
    tab.setAttribute("data-workflow-id", workflow.id);
    tab.tabIndex = selected ? 0 : -1;
    tab.addEventListener("click", () => select(workflow.id));
    tab.addEventListener("keydown", (event) => {
      const keyOffsets = {
        ArrowLeft: -1,
        ArrowRight: 1,
      };
      let nextIndex = null;
      if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = workflows.length - 1;
      else if (Object.hasOwn(keyOffsets, event.key)) {
        nextIndex = (
          index + keyOffsets[event.key] + workflows.length
        ) % workflows.length;
      }
      if (nextIndex === null) return;
      event.preventDefault();
      const nextId = workflows[nextIndex].id;
      select(nextId);
      focusRenderedTab(nextId);
      Promise.resolve().then(() => focusRenderedTab(nextId));
    });
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
  dialog.setAttribute("aria-label", spec.title);
  const heading = el(documentNode, "div", "workflow-dialog-heading");
  heading.appendChild(el(
    documentNode, "h2", "workflow-dialog-title", spec.title,
  ));
  dialog.appendChild(heading);
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
  error.setAttribute("role", "alert");
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
  const dismiss = () => {
    if (dialog.attributes?.get?.("aria-busy") === "true" ||
        dialog.getAttribute?.("aria-busy") === "true") return;
    spec.cancel();
  };
  cancel.addEventListener("click", dismiss);
  confirm.addEventListener("click", async () => {
    cancel.disabled = true;
    confirm.disabled = true;
    dialog.setAttribute("aria-busy", "true");
    confirm.textContent = spec.pendingText || "Saving…";
    error.hidden = true;
    try {
      await spec.confirm();
    } catch (failure) {
      cancel.disabled = false;
      confirm.disabled = false;
      dialog.setAttribute("aria-busy", "false");
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
    if (event.target === backdrop) dismiss();
  });
  host.appendChild(backdrop);
  mountWorkflowDialog({
    documentNode,
    host,
    dialog,
    dismiss,
    initialFocus: cancel,
  });
}
