import {
  el,
  loadSection,
  renderTable,
  section,
} from "./universe_view_support.js";
import {
  commandPanel,
  detailColumns,
  factsPanel,
  itemHeading,
  markdownSection,
  posturePanel,
  progressPanel,
  textPanel,
  verificationPanel,
  withoutMarkdownSections,
} from "./item_view_primitives.js";

function issuePanels(documentNode, item) {
  const spec = item.narrative.spec || item.narrative.body;
  const acceptance = markdownSection(spec, "Acceptance Criteria");
  return detailColumns(
    documentNode,
    [
      textPanel(
        documentNode,
        "Spec",
        withoutMarkdownSections(
          spec,
          ["Acceptance Criteria", "Progress Log", "File Budget"],
        ),
      ),
      textPanel(
        documentNode,
        "Acceptance criteria",
        acceptance,
        "No acceptance criteria recorded.",
      ),
    ],
    [
      factsPanel(documentNode, item),
      verificationPanel(documentNode, item),
      posturePanel(documentNode, item),
      commandPanel(documentNode, item),
      progressPanel(documentNode, item),
    ],
  );
}

function renderEpicTasks(context, item, panel) {
  loadSection(
    context,
    panel,
    "epic_tasks.list.run",
    {},
    (body, callResult) => {
      const rows = (callResult.envelope.result || {}).tasks || [];
      panel.setCount(rows.length);
      renderTable(body, rows, [
        { label: "No", value: (row) => row.task_num, mono: true },
        { label: "Task", value: (row) => row.title },
        { label: "Status", value: (row) => row.status, pill: true },
      ], "No tasks yet.");
    },
    {
      kind: "epic_task",
      epic_id: Number(item.id),
      project_id: String(item.project.id),
    },
  );
}

function epicPanels(context, documentNode, item) {
  const tasks = section(documentNode, "Tasks");
  renderEpicTasks(context, item, tasks);
  return detailColumns(
    documentNode,
    [
      tasks,
      textPanel(
        documentNode,
        "Shepherd log",
        item.narrative.shepherd_log,
        "No shepherd verdict recorded.",
      ),
      textPanel(
        documentNode,
        "Worktree plan",
        item.narrative.worktree_plan,
        "No worktree plan recorded.",
      ),
    ],
    [
      factsPanel(documentNode, item),
      verificationPanel(documentNode, item),
      posturePanel(documentNode, item),
      commandPanel(documentNode, item),
    ],
  );
}

function dashPanels(documentNode, item) {
  return detailColumns(
    documentNode,
    [
      textPanel(
        documentNode,
        "Instruction",
        item.narrative.spec || item.narrative.body,
        "No instruction recorded.",
      ),
      verificationPanel(documentNode, item),
    ],
    [
      factsPanel(documentNode, item),
      posturePanel(documentNode, item),
      commandPanel(documentNode, item),
    ],
  );
}

function fallbackPanels(documentNode, item) {
  return detailColumns(
    documentNode,
    [textPanel(documentNode, "Item", item.narrative.body)],
    [
      factsPanel(documentNode, item),
      verificationPanel(documentNode, item),
      posturePanel(documentNode, item),
      commandPanel(documentNode, item),
    ],
  );
}

export function renderWorkflowItemDetail(context, main, item) {
  const documentNode = context.document;
  const host = el(documentNode, "div", "item-detail");
  host.appendChild(itemHeading(documentNode, item));
  if (item.blocked && item.blocked_reason) {
    const blocked = el(documentNode, "div", "item-blocked");
    blocked.appendChild(el(documentNode, "strong", null, "Blocked"));
    blocked.appendChild(el(
      documentNode, "span", null, item.blocked_reason,
    ));
    host.appendChild(blocked);
  }
  if (item.workflow.id === "issue") {
    host.appendChild(issuePanels(documentNode, item));
  } else if (item.workflow.id === "epic") {
    host.appendChild(epicPanels(context, documentNode, item));
  } else if (item.workflow.id === "dash") {
    host.appendChild(dashPanels(documentNode, item));
  } else {
    host.appendChild(fallbackPanels(documentNode, item));
  }
  main.replaceChildren(host);
}
