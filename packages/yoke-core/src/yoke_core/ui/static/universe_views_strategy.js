import { buildUniverseRoute } from "./universe_navigation.js";
import {
  button,
} from "./workflow_view_primitives.js";
import {
  documentReviewView,
  historyReviewView,
} from "./strategy_view_primitives.js";
import {
  stateActionsPanel,
  strategyReviewCallout,
  strategyStats,
  strategyWriteActivity,
} from "./strategy_view_summary.js";
import {
  el,
  loadScopedSection,
  loadSection,
  scopeBuckets,
  section,
  statePill,
  withProjectColumn,
} from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";

function executionLabel(doc) {
  if (doc.execution_state === "claimed") {
    return `claimed · ${doc.execution_item_ref || `item ${doc.execution_item_id}`}`;
  }
  return doc.archived ? "archived" : doc.execution_state || "available";
}

function scopeLabel(scope, slugById) {
  if (scope === "all") return "across all projects";
  const projects = scope.map(
    (projectId) => slugById.get(String(projectId)) || String(projectId),
  );
  return `scoped to ${projects.join(" + ")}`;
}

function strategyCell(documentNode, tag, className, text) {
  return el(documentNode, tag, className, text);
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

function makeRowNavigable(documentNode, row, href, label) {
  row.tabIndex = 0;
  row.setAttribute("role", "link");
  row.setAttribute("aria-label", `Open ${label}`);
  row.addEventListener("click", (event) => {
    if (eventCameFromControl(event, row)) return;
    documentNode.defaultView.location.hash = href;
  });
  row.addEventListener("keydown", (event) => {
    if (eventCameFromControl(event, row)) return;
    if (!["Enter", " "].includes(event.key)) return;
    if (typeof event.preventDefault === "function") event.preventDefault();
    documentNode.defaultView.location.hash = href;
  });
}

function renderStrategyTable(documentNode, body, docs, scope) {
  if (docs.length === 0) {
    body.appendChild(el(
      documentNode, "p", "empty", "No strategy documents yet.",
    ));
    return;
  }
  const table = el(documentNode, "table", "items strategy-corpus-table");
  const columns = withProjectColumn([
    { label: "Doc" },
    { label: "Purpose / ancestry" },
    { label: "Last editor" },
    { label: "Last write" },
    { label: "Revisions" },
    { label: "Execution" },
  ], scope, (doc) => doc.project || doc.project_id || "—");
  const projectColumn = columns.find((column) => column.label === "project");
  const head = el(documentNode, "tr");
  for (const column of columns) {
    head.appendChild(el(documentNode, "th", null, column.label));
  }
  table.appendChild(head);
  for (const doc of docs) {
    const row = el(documentNode, "tr", "strategy-corpus-row");
    const href = buildUniverseRoute(
      "strategy", doc.project_id, doc.slug,
    );

    const slugCell = el(documentNode, "td", "mono");
    const slug = el(documentNode, "a", "row-link strategy-doc-link", doc.slug);
    slug.href = href;
    slugCell.appendChild(slug);
    if (doc.archived) {
      const archived = statePill(documentNode, "archived");
      archived.className += " strategy-archived";
      slugCell.appendChild(archived);
    }
    row.appendChild(slugCell);
    if (projectColumn) {
      row.appendChild(strategyCell(
        documentNode,
        "td",
        "strategy-project",
        projectColumn.value(doc),
      ));
    }

    const purpose = el(documentNode, "td");
    purpose.appendChild(strategyCell(
      documentNode, "div", "strategy-doc-title", doc.title,
    ));
    const ancestry = el(documentNode, "div", "strategy-doc-ancestry");
    if (doc.parent_slug) {
      ancestry.appendChild(strategyCell(
        documentNode, "span", null, "child of ",
      ));
      ancestry.appendChild(strategyCell(
        documentNode, "span", "mono", doc.parent_slug,
      ));
    } else {
      ancestry.textContent = "top-level strategy";
    }
    purpose.appendChild(ancestry);
    row.appendChild(purpose);

    const editor = el(documentNode, "td", "strategy-editor");
    if (doc.updated_by) {
      editor.appendChild(strategyCell(
        documentNode, "span", "strategy-editor-avatar",
        String(doc.updated_by).slice(0, 1),
      ));
      editor.appendChild(strategyCell(
        documentNode, "span", "strategy-editor-name", doc.updated_by,
      ));
    }
    row.appendChild(editor);
    const lastWrite = el(documentNode, "td", "strategy-last-write");
    lastWrite.appendChild(relativeTime(documentNode, doc.updated_at));
    row.appendChild(lastWrite);
    row.appendChild(strategyCell(
      documentNode, "td", "mono strategy-revision-count", doc.revisions,
    ));
    const execution = el(documentNode, "td");
    const state = statePill(
      documentNode,
      doc.archived ? "archived" : doc.execution_state || "available",
      executionLabel(doc),
    );
    if (state) execution.appendChild(state);
    row.appendChild(execution);
    makeRowNavigable(documentNode, row, href, doc.slug);
    table.appendChild(row);
  }
  body.appendChild(table);
}

export function renderStrategyView(context, main, scope) {
  const documentNode = context.document;
  const statsHost = el(documentNode, "div", "strategy-stats-host");
  const callout = strategyReviewCallout(documentNode);
  const panel = section(documentNode, "Strategy corpus", { showRaw: false });
  const writesHost = el(documentNode, "div", "strategy-writes-host");
  main.replaceChildren(statsHost, callout, panel, writesHost);
  const projects = context.projects();
  const buckets = scopeBuckets(scope, projects, true);
  const slugById = new Map(
    projects.map((row) => [String(row.id), row.slug || String(row.id)]),
  );
  loadScopedSection(
    context,
    panel,
    buckets.map((bucket) => ({
      functionId: "strategy.surface.list",
      payload: {},
      target: { kind: "global", project_id: String(bucket) },
    })),
    (body, callResults) => {
      const docs = callResults.flatMap((callResult, index) => (
        ((callResult.envelope.result || {}).docs || []).map((doc) => ({
          ...doc,
          project: slugById.get(buckets[index]) || buckets[index],
          project_id: buckets[index],
        }))
      ));
      panel.setCount(scopeLabel(scope, slugById));
      statsHost.replaceChildren(strategyStats(documentNode, docs));
      const writes = callResults.flatMap(
        (callResult) => (callResult.envelope.result || {}).writes || [],
      );
      writesHost.replaceChildren(
        strategyWriteActivity(documentNode, writes),
      );
      renderStrategyTable(documentNode, body, docs, scope);
    },
  );
}

function renderDetail(context, main, projectId, doc) {
  const documentNode = context.document;
  let selectedTab = "document";
  const host = el(documentNode, "div", "strategy-detail");
  const heading = el(
    documentNode, "div", "page-head item-detail-heading",
  );
  const headingCopy = el(
    documentNode, "div", "h item-detail-heading-copy",
  );
  headingCopy.appendChild(el(documentNode, "h1", "title", doc.slug));
  heading.appendChild(headingCopy);
  const actions = stateActionsPanel(
    context,
    projectId,
    doc,
    () => renderStrategyDocDetailView(
      context, main, projectId, doc.slug,
    ),
  );
  const tabs = el(documentNode, "div", "strategy-tabs");
  tabs.setAttribute("role", "tablist");
  const content = el(documentNode, "div", "strategy-tab-content");
  content.id = "strategy-tab-content";
  content.setAttribute("role", "tabpanel");
  const draw = () => {
    tabs.replaceChildren();
    const definitions = [
      ["document", "Document"],
      ["history", "History"],
    ];
    for (const [index, [id, label]] of definitions.entries()) {
      const tab = button(
        documentNode,
        label,
        `workflow-tab${selectedTab === id ? " selected" : ""}`,
      );
      tab.id = `strategy-tab-${id}`;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(selectedTab === id));
      tab.setAttribute("aria-controls", content.id);
      tab.tabIndex = selectedTab === id ? 0 : -1;
      tab.addEventListener("click", () => {
        selectedTab = id;
        draw();
      });
      tab.addEventListener("keydown", (event) => {
        const delta = event.key === "ArrowRight"
          ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!delta && !["Home", "End"].includes(event.key)) return;
        if (typeof event.preventDefault === "function") event.preventDefault();
        const next = event.key === "Home"
          ? 0
          : event.key === "End"
            ? definitions.length - 1
            : (index + delta + definitions.length) % definitions.length;
        selectedTab = definitions[next][0];
        draw();
        const selected = tabs.children[next];
        if (typeof selected?.focus === "function") selected.focus();
      });
      tabs.appendChild(tab);
    }
    content.setAttribute("aria-labelledby", `strategy-tab-${selectedTab}`);
    content.replaceChildren(
      selectedTab === "history"
        ? historyReviewView(
          context,
          projectId,
          doc,
          () => renderStrategyDocDetailView(
            context, main, projectId, doc.slug,
          ),
        )
        : documentReviewView(documentNode, doc),
    );
  };
  draw();
  host.appendChild(heading);
  host.appendChild(actions);
  host.appendChild(tabs);
  host.appendChild(content);
  main.replaceChildren(host);
}

export function renderStrategyDocDetailView(
  context,
  main,
  projectId,
  slug,
) {
  const loading = section(
    context.document, String(slug), { showRaw: false },
  );
  main.replaceChildren(loading);
  loadSection(
    context,
    loading,
    "strategy.surface.get",
    { slug: String(slug) },
    (_body, callResult) => {
      const result = callResult.envelope.result || {};
      renderDetail(context, main, projectId, {
        ...(result.document || {}),
        project_slug: result.project_slug,
      });
    },
    { kind: "global", project_id: String(projectId) },
  );
}
