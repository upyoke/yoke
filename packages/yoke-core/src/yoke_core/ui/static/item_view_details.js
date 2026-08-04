import { buildUniverseRoute } from "./universe_navigation.js";
import {
  el,
  loadSection,
  renderTable,
  section,
} from "./universe_view_support.js";
import {
  actionLink,
  commandPanel,
  detailColumns,
  factsPanel,
  filledNarrativePanels,
  itemHeading,
  markdownSection,
  posturePanel,
  progressIfPresent,
  progressPanel,
  textPanel,
  verificationPanel,
  withoutMarkdownSections,
} from "./item_view_primitives.js";
import { workflowPanel } from "./workflow_view_primitives.js";

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
      ...filledNarrativePanels(documentNode, item),
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

function renderEpicTasks(context, item, panel, progress) {
  loadSection(
    context,
    panel,
    "epic_tasks.list.run",
    {},
    (body, callResult) => {
      const rows = (callResult.envelope.result || {}).tasks || [];
      panel.setCount(rows.length);
      const completed = rows.filter((row) => (
        ["done", "completed", "succeeded"].includes(
          String(row.status || "").toLowerCase(),
        )
      )).length;
      progress.textContent = `${completed} of ${rows.length} done`;
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
  const tasks = section(documentNode, "Tasks", { showRaw: false });
  tasks.className += " item-epic-tasks";
  const progress = el(
    documentNode, "span", "workflow-panel-detail", "loading progress…",
  );
  tasks.children[0].appendChild(progress);
  renderEpicTasks(context, item, tasks, progress);
  const progressLog = progressIfPresent(documentNode, item);
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
        { detail: "intent · lanes activate per task at conduct" },
      ),
      ...filledNarrativePanels(
        documentNode,
        item,
        ["shepherd_log", "worktree_plan"],
      ),
    ],
    [
      factsPanel(documentNode, item),
      verificationPanel(documentNode, item),
      posturePanel(documentNode, item),
      commandPanel(documentNode, item),
      ...(progressLog ? [progressLog] : []),
    ],
  );
}

function sourceFieldNotePanel(documentNode, item) {
  const note = item.source_field_note;
  if (!note) return null;
  const { panel, body } = workflowPanel(
    documentNode,
    "Promoted from field note",
    { detail: note.category },
  );
  body.appendChild(el(
    documentNode,
    "p",
    "item-muted",
    note.context || "The note remains the supporting observation.",
  ));
  body.appendChild(actionLink(
    documentNode,
    `Open field note #${note.entry_id}`,
    buildUniverseRoute(
      "ouroboros",
      note.project_id || item.project.id,
      String(note.entry_id),
    ),
  ));
  return panel;
}

function dashPanels(documentNode, item) {
  const origin = sourceFieldNotePanel(documentNode, item);
  const progressLog = progressIfPresent(documentNode, item);
  return detailColumns(
    documentNode,
    [
      textPanel(
        documentNode,
        "Instruction",
        item.narrative.spec || item.narrative.body,
        "No instruction recorded.",
      ),
      ...filledNarrativePanels(documentNode, item),
      verificationPanel(documentNode, item),
    ],
    [
      factsPanel(documentNode, item),
      ...(origin ? [origin] : []),
      posturePanel(documentNode, item),
      commandPanel(documentNode, item),
      ...(progressLog ? [progressLog] : []),
    ],
  );
}

function fallbackPanels(documentNode, item) {
  const body = String(item.narrative?.body || "").trim();
  const spec = String(item.narrative?.spec || "").trim();
  const primary = body
    ? [textPanel(documentNode, "Item", item.narrative.body)]
    : spec
      ? [textPanel(documentNode, "Spec", item.narrative.spec)]
      : [];
  const progressLog = progressIfPresent(documentNode, item);
  return detailColumns(
    documentNode,
    [
      ...primary,
      ...filledNarrativePanels(documentNode, item),
    ],
    [
      factsPanel(documentNode, item),
      verificationPanel(documentNode, item),
      posturePanel(documentNode, item),
      commandPanel(documentNode, item),
      ...(progressLog ? [progressLog] : []),
    ],
  );
}

export function renderWorkflowItemDetail(context, main, item) {
  const documentNode = context.document;
  const workflowId = String(item.workflow.id || "").toLowerCase();
  const host = el(
    documentNode,
    "div",
    `item-detail ${workflowId || "workflow"}-detail`,
  );
  host.appendChild(itemHeading(documentNode, item));
  if (item.blocked && item.blocked_reason) {
    const blocked = el(documentNode, "div", "item-blocked");
    blocked.appendChild(el(documentNode, "strong", null, "Blocked"));
    blocked.appendChild(el(
      documentNode, "span", null, item.blocked_reason,
    ));
    host.appendChild(blocked);
  }
  if (workflowId === "issue") {
    host.appendChild(issuePanels(documentNode, item));
  } else if (workflowId === "epic") {
    host.appendChild(epicPanels(context, documentNode, item));
  } else if (workflowId === "dash") {
    host.appendChild(dashPanels(documentNode, item));
  } else {
    host.appendChild(fallbackPanels(documentNode, item));
  }
  main.replaceChildren(host);
}
