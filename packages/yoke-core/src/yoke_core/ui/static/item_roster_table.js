import { attachTooltip } from "./universe_tooltip.js";
import { el, labelCellsByColumn, statePill, withProjectColumn } from "./universe_view_support.js";
import { relativeAgePhrase, relativeTime } from "./universe_time.js";
import { sortHeader } from "./item_roster_sort.js";

function claimLabel(row) {
  const claim = row.claimed_by;
  return claim ? (claim.actor_label || claim.session_id || "") : "";
}

function projectLabel(projects, row) {
  const rowLabel = row.project_slug || row.project;
  const rowKey = row.project_id ?? rowLabel;
  const project = projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value) === String(rowKey),
    )
  ));
  return String(
    rowLabel || project?.slug || project?.name || row.project_id || "—",
  );
}

function eventCameFromControl(event, row) {
  let target = event.target;
  while (target && target !== row) {
    if (["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "TIME"].includes(
      String(target.tagName || "").toUpperCase(),
    )) return true;
    target = target.parentNode;
  }
  return false;
}

function makeRowNavigable(documentNode, row, href) {
  row.tabIndex = 0;
  row.setAttribute("role", "link");
  row.setAttribute("aria-label", `Open ${row.children[0]?.textContent || "item"}`);
  row.addEventListener("click", (event) => {
    if (eventCameFromControl(event, row)) return;
    documentNode.defaultView.location.href = href;
  });
  row.addEventListener("keydown", (event) => {
    if (eventCameFromControl(event, row)) return;
    if (!["Enter", " "].includes(event.key)) return;
    if (typeof event.preventDefault === "function") event.preventDefault();
    documentNode.defaultView.location.href = href;
  });
}

export function itemTable(documentNode, rows, rowHref, scope, projects, sort, onSort) {
  const table = el(documentNode, "table", "items item-roster table-stacks-narrow");
  const columns = withProjectColumn([
    { label: "ID" },
    { label: "Title" },
    { label: "Workflow" },
    { label: "Status" },
    { label: "Owner" },
    { label: "Claimed by" },
    { label: "Last updated" },
  ], scope, (row) => projectLabel(projects, row));
  const projectColumn = columns.find((column) => column.label === "project");
  const head = el(documentNode, "tr", "item-roster-sort");
  for (const column of columns) {
    head.appendChild(sortHeader(documentNode, column.label, sort, onSort));
  }
  table.appendChild(head);
  for (const row of rows) {
    const href = rowHref(row);
    const tr = el(documentNode, "tr", "item-roster-row");
    const refCell = el(documentNode, "td", "mono");
    const link = el(documentNode, "a", "row-link", row.public_ref);
    link.href = href;
    refCell.appendChild(link);
    tr.appendChild(refCell);
    if (projectColumn) {
      tr.appendChild(el(
        documentNode,
        "td",
        "item-project",
        projectColumn.value(row),
      ));
    }
    const titleCell = el(documentNode, "td", "item-roster-title");
    const titleLink = el(
      documentNode, "a", "item-title-link", row.title,
    );
    titleLink.href = href;
    titleCell.appendChild(titleLink);
    if (row.workflow_id !== "task" && row.qa_attention?.verdict === "undetermined") {
      const reason = String(row.qa_attention.verdict_reason || "").trim();
      const attention = el(
        documentNode, "span", "item-workflow",
        reason ? `QA undetermined — ${reason}` : "QA undetermined",
      );
      attachTooltip(documentNode, attention, reason);
      titleCell.appendChild(attention);
    }
    tr.appendChild(titleCell);
    const workflowCell = el(documentNode, "td");
    const workflow = el(
      documentNode,
      "span",
      `item-workflow ${String(row.workflow_id || "").toLowerCase()}`,
      row.workflow_id,
    );
    workflow.setAttribute("data-workflow", row.workflow_id);
    attachTooltip(documentNode, workflow, `workflow · ${row.workflow_id}`);
    workflowCell.appendChild(workflow);
    tr.appendChild(workflowCell);
    const statusCell = el(documentNode, "td");
    const status = statePill(
      documentNode,
      row.status,
      row.stage_label || row.status,
    );
    if (status) statusCell.appendChild(status);
    tr.appendChild(statusCell);
    tr.appendChild(el(
      documentNode,
      "td",
      "item-muted",
      row.owner || "unassigned",
    ));
    const claimCell = el(documentNode, "td", "item-muted");
    const claimedBy = claimLabel(row);
    if (claimedBy) {
      const claimContent = el(documentNode, "span");
      claimContent.appendChild(el(
        documentNode,
        "span",
        "item-claim-avatar",
        claimedBy.slice(0, 1).toUpperCase(),
      ));
      claimContent.appendChild(el(
        documentNode, "span", null, claimedBy,
      ));
      claimCell.appendChild(claimContent);
    } else {
      claimCell.textContent = "—";
    }
    tr.appendChild(claimCell);
    const updated = el(documentNode, "td", "item-updated");
    updated.appendChild(row.updated_at ? relativeTime(documentNode, row.updated_at, Date.now(), { relativeAgeFn: relativeAgePhrase }) : el(documentNode, "span", null, "—"));
    tr.appendChild(updated);
    labelCellsByColumn(tr, columns.map((column) => column.label));
    if (href) makeRowNavigable(documentNode, tr, href);
    table.appendChild(tr);
  }
  const wrap = el(documentNode, "div", "table-wrap item-roster-wrap");
  wrap.appendChild(table);
  if (!rows.length) wrap.appendChild(el(documentNode, "p", "empty", "No items match this view."));
  return wrap;
}
