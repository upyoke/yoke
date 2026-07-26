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
} from "./universe_view_support.js";
import { relativeAge } from "./universe_time.js";

function executionLabel(doc) {
  if (doc.execution_state === "claimed") {
    return `claimed · ${doc.execution_item_ref || `item ${doc.execution_item_id}`}`;
  }
  return doc.archived ? "archived" : doc.execution_state;
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

function renderStrategyTable(documentNode, body, docs) {
  if (docs.length === 0) {
    body.appendChild(el(
      documentNode, "p", "empty", "No strategy documents yet.",
    ));
    return;
  }
  const table = el(documentNode, "table", "items strategy-corpus-table");
  const head = el(documentNode, "tr");
  for (const label of [
    "Doc", "Purpose / ancestry", "Last editor", "Last write",
    "Revisions", "Execution",
  ]) {
    head.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(head);
  for (const doc of docs) {
    const row = el(documentNode, "tr", "strategy-corpus-row");

    const slugCell = el(documentNode, "td", "mono");
    const slug = el(documentNode, "a", "row-link strategy-doc-link", doc.slug);
    slug.href = buildUniverseRoute(
      "strategy", doc.project_id, doc.slug,
    );
    slugCell.appendChild(slug);
    if (doc.archived) {
      slugCell.appendChild(strategyCell(
        documentNode, "span", "strategy-archived", "archived",
      ));
    }
    row.appendChild(slugCell);

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
    row.appendChild(strategyCell(
      documentNode, "td", "strategy-last-write",
      relativeAge(doc.updated_at),
    ));
    row.appendChild(strategyCell(
      documentNode, "td", "mono strategy-revision-count", doc.revisions,
    ));
    const execution = el(documentNode, "td");
    const state = el(
      documentNode,
      "span",
      `pill ${doc.execution_state === "claimed" ? "run" : "idle"}`,
      executionLabel(doc),
    );
    execution.appendChild(state);
    row.appendChild(execution);
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
      renderStrategyTable(documentNode, body, docs);
    },
  );
}

function renderDetail(context, main, projectId, doc) {
  const documentNode = context.document;
  let selectedTab = "document";
  const host = el(documentNode, "div", "strategy-detail");
  const heading = el(documentNode, "div", "item-detail-heading");
  const headingCopy = el(documentNode, "div", "item-detail-heading-copy");
  headingCopy.appendChild(el(documentNode, "h1", null, doc.slug));
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
  const draw = () => {
    tabs.replaceChildren();
    for (const [id, label] of [
      ["document", "Document"],
      ["history", "History"],
    ]) {
      const tab = button(
        documentNode,
        label,
        `workflow-tab${selectedTab === id ? " selected" : ""}`,
      );
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(selectedTab === id));
      tab.addEventListener("click", () => {
        selectedTab = id;
        draw();
      });
      tabs.appendChild(tab);
    }
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
