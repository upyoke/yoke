import { el } from "./universe_view_support.js";
import { callFunction } from "./universe_view_support.js";
import { button, formatTimestamp, workflowPanel } from "./workflow_view_primitives.js";

function inspectionNode(row) {
  return Array.from(row.children).find(
    (node) => node.classList.contains("workflow-version-inspection"),
  );
}

function renderInspection(documentNode, row, result, makeCurrent) {
  const inspection = el(
    documentNode, "div", "workflow-version-inspection",
  );
  inspection.appendChild(el(
    documentNode,
    "code",
    "workflow-version-digest",
    result.definition_digest || "digest unavailable",
  ));
  const stages = (result.definition?.stages || [])
    .map((stage) => stage.label || stage.id)
    .join(" → ");
  if (stages) {
    inspection.appendChild(el(
      documentNode, "p", "workflow-version-stages", stages,
    ));
  }
  const makeCurrentButton = button(
    documentNode, "Make current", "workflow-button compact",
  );
  makeCurrentButton.addEventListener("click", makeCurrent);
  inspection.appendChild(makeCurrentButton);
  row.appendChild(inspection);
}

function inspectButton(documentNode, row, workflow, version, actions) {
  const inspect = button(
    documentNode, "Inspect", "workflow-button compact",
  );
  inspect.addEventListener("click", async () => {
    row.classList.toggle("inspecting");
    const existing = inspectionNode(row);
    if (existing) {
      row.removeChild(existing);
      return;
    }
    const loading = el(
      documentNode, "div", "workflow-version-inspection", "Loading version…",
    );
    row.appendChild(loading);
    let callResult;
    try {
      callResult = await callFunction(
        actions.client,
        "workflows.version.get",
        { workflow_id: workflow.id, version: Number(version.version) },
      );
    } catch (failure) {
      loading.textContent = String(failure);
      loading.classList.add("error");
      return;
    }
    const ok = callResult.status === 200 && callResult.envelope.success;
    if (!ok) {
      loading.textContent = callResult.envelope?.error?.message ||
        "Version read failed.";
      loading.classList.add("error");
      return;
    }
    row.removeChild(loading);
    renderInspection(
      documentNode,
      row,
      callResult.envelope.result || {},
      () => actions.makeCurrent(version),
    );
  });
  return inspect;
}

function versionRow(documentNode, workflow, version, actions) {
  const current = Number(version.version) ===
    Number(workflow.current_version);
  const row = el(documentNode, "div", "workflow-version-row");
  row.appendChild(el(
    documentNode,
    "span",
    `workflow-version-dot${current ? " current" : ""}`,
  ));
  const summary = el(documentNode, "div", "workflow-version-summary");
  summary.appendChild(el(
    documentNode,
    "div",
    "workflow-version-title",
    `v${version.version}${current ? " · current" : ""}`,
  ));
  summary.appendChild(el(
    documentNode,
    "div",
    "workflow-version-description",
    current
      ? "New items pin this version."
      : "Readable and eligible to become current again.",
  ));
  row.appendChild(summary);
  row.appendChild(el(
    documentNode,
    "time",
    "workflow-version-when",
    formatTimestamp(version.published_at),
  ));
  if (!current) {
    row.appendChild(inspectButton(
      documentNode, row, workflow, version, actions,
    ));
  }
  return row;
}

export function renderVersionHistory(documentNode, workflow, actions) {
  const versions = [...(workflow.versions || [])].sort(
    (left, right) => Number(right.version) - Number(left.version),
  );
  const { panel, body } = workflowPanel(documentNode, "Version history");
  const timeline = el(documentNode, "div", "workflow-version-timeline");
  for (const version of versions) {
    timeline.appendChild(versionRow(
      documentNode, workflow, version, actions,
    ));
  }
  if (!versions.length) {
    timeline.appendChild(el(
      documentNode, "p", "empty", "No published versions.",
    ));
  } else if (versions.length === 1) {
    timeline.appendChild(el(
      documentNode,
      "p",
      "workflow-first-version",
      "First published version.",
    ));
  }
  body.appendChild(timeline);
  return panel;
}
