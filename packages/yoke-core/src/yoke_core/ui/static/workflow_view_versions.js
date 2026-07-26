import { el } from "./universe_view_support.js";
import {
  button,
  formatTimestamp,
  workflowPanel,
} from "./workflow_view_primitives.js";

function inspectionNode(row) {
  return Array.from(row.children).find(
    (node) => node.classList.contains("workflow-version-inspection"),
  );
}

function inspectButton(documentNode, row, version) {
  const inspect = button(
    documentNode, "Inspect", "workflow-button compact",
  );
  inspect.addEventListener("click", () => {
    row.classList.toggle("inspecting");
    const existing = inspectionNode(row);
    if (existing) {
      row.removeChild(existing);
      return;
    }
    row.appendChild(el(
      documentNode,
      "code",
      "workflow-version-inspection",
      version.definition_digest || "digest unavailable",
    ));
  });
  return inspect;
}

function versionRow(documentNode, workflow, version) {
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
  if (!current) row.appendChild(inspectButton(documentNode, row, version));
  return row;
}

export function renderVersionHistory(documentNode, workflow) {
  const versions = [...(workflow.versions || [])].sort(
    (left, right) => Number(right.version) - Number(left.version),
  );
  const { panel, body } = workflowPanel(documentNode, "Version history");
  const timeline = el(documentNode, "div", "workflow-version-timeline");
  for (const version of versions) {
    timeline.appendChild(versionRow(documentNode, workflow, version));
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
