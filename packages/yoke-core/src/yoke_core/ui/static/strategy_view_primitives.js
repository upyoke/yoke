import {
  callFunction,
  el,
} from "./universe_view_support.js";
import { renderMarkdown } from "./markdown_view.js";
import { relativeTime } from "./universe_time.js";
import {
  button,
  workflowPanel,
} from "./workflow_view_primitives.js";

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  const digits = bytes < 10240 ? 1 : 0;
  return `${(bytes / 1024).toFixed(digits)} KB`;
}

export function renderDocumentBody(documentNode, content, documentHeadings = []) {
  return renderMarkdown(documentNode, content, {
    className: "rich-text strategy-document",
    emptyText: "No content yet.",
    omitLeadingHeading: documentHeadings,
    demoteHeadings: true,
  });
}

export function documentReviewView(documentNode, doc) {
  const split = el(documentNode, "div", "strategy-split");
  const current = workflowPanel(documentNode, "Current document");
  current.panel.children[0].children[0].appendChild(el(
    documentNode,
    "span",
    "strategy-revision-chip",
    doc.current_revision ? `revision ${doc.current_revision}` : "unrevised",
  ));
  const meta = el(documentNode, "div", "workflow-panel-meta");
  const detail = el(documentNode, "span", "workflow-panel-detail");
  detail.appendChild(el(
    documentNode, "span", null, `${formatBytes(doc.bytes)} · updated `,
  ));
  if (doc.updated_at) {
    detail.appendChild(relativeTime(documentNode, doc.updated_at));
  } else {
    detail.appendChild(el(documentNode, "span", null, "recently"));
  }
  meta.appendChild(detail);
  current.panel.children[0].appendChild(meta);
  current.body.appendChild(renderDocumentBody(
    documentNode,
    doc.content,
    [doc.slug, doc.title].filter(Boolean),
  ));
  split.appendChild(current.panel);

  const harness = workflowPanel(documentNode, "Author through a harness");
  harness.body.className += " item-stack strategy-harness";
  for (const command of [
    `yoke strategy render --project ${doc.project_slug || "PROJECT"}`,
    `yoke strategy ingest ${doc.slug} --dry-run`,
  ]) {
    harness.body.appendChild(el(
      documentNode, "code", "item-command", command,
    ));
  }
  harness.body.appendChild(el(
    documentNode,
    "p",
    "item-muted",
    "Inspect documents, compare revisions, and approve requested reviews here; open-ended edits stay in the harness where the plan and repository can be understood together.",
  ));
  split.appendChild(harness.panel);
  return split;
}

function revisionRow(documentNode, revision, current) {
  const row = el(documentNode, "div", "strategy-revision");
  row.appendChild(el(
    documentNode,
    "span",
    `strategy-revision-dot${current ? " current" : ""}`,
  ));
  const copy = el(documentNode, "div", "strategy-revision-copy");
  const operationFamily = String(
    revision.source_operation || "updated",
  ).split(":", 1)[0];
  const operation = String(
    revision.operation_label || {
      create: "created",
      ingest: "ingested",
      replace: "replaced",
      restore: "restored",
      coordination_append: "updated",
    }[operationFamily] || operationFamily,
  ).replace(/[._-]+/g, " ").toLowerCase();
  copy.appendChild(el(
    documentNode,
    "strong",
    null,
    `Revision ${revision.revision} · ${current ? "current" : operation}`,
  ));
  const summary = el(documentNode, "span", "item-muted");
  summary.appendChild(el(
    documentNode,
    "span",
    null,
    [
      revision.change_summary || `Document ${operation}`,
      formatBytes(revision.byte_length),
    ].filter(Boolean).join(" · "),
  ));
  summary.appendChild(el(documentNode, "span", null, " · "));
  summary.appendChild(el(
    documentNode,
    "span",
    "mono",
    `${String(revision.content_sha256).slice(0, 8)}…`,
  ));
  copy.appendChild(summary);
  row.appendChild(copy);
  const created = el(documentNode, "span", "item-muted");
  created.appendChild(relativeTime(documentNode, revision.created_at));
  row.appendChild(created);
  return row;
}

function revisionSelect(documentNode, revisions, selected) {
  const select = el(documentNode, "select", "strategy-revision-select");
  for (const revision of revisions) {
    const option = el(
      documentNode, "option", null, `revision ${revision.revision}`,
    );
    option.value = String(revision.revision);
    option.selected = Number(revision.revision) === Number(selected);
    select.appendChild(option);
  }
  select.value = String(selected ?? "");
  return select;
}

export function historyReviewView(
  context,
  projectId,
  doc,
  refresh,
) {
  const documentNode = context.document;
  const split = el(documentNode, "div", "strategy-split");
  const timeline = workflowPanel(
    documentNode, "Revision history", { count: doc.revisions.length },
  );
  timeline.body.className += " strategy-timeline";
  for (const [index, revision] of doc.revisions.entries()) {
    timeline.body.appendChild(revisionRow(documentNode, revision, index === 0));
  }
  if (!doc.revisions.length) {
    timeline.body.appendChild(el(
      documentNode, "p", "empty", "No authored revisions yet.",
    ));
  }
  split.appendChild(timeline.panel);

  const compare = workflowPanel(documentNode, "Compare or restore");
  compare.body.className += " item-stack";
  const oldest = doc.revisions.at(-1)?.revision;
  const newest = doc.revisions[0]?.revision;
  const controls = el(documentNode, "div", "strategy-compare-controls");
  const from = revisionSelect(documentNode, doc.revisions, oldest);
  const to = revisionSelect(documentNode, doc.revisions, newest);
  controls.appendChild(el(documentNode, "label", null, "From"));
  controls.appendChild(from);
  controls.appendChild(el(documentNode, "label", null, "To"));
  controls.appendChild(to);
  controls.appendChild(el(documentNode, "label", null, "Change"));
  const change = el(documentNode, "span", "strategy-change-summary");
  controls.appendChild(change);
  compare.body.appendChild(controls);
  const actions = el(documentNode, "div", "strategy-actions");
  const view = button(documentNode, "View diff", "item-action");
  const restore = button(
    documentNode,
    `Restore revision ${oldest || ""}…`,
    "item-action",
  );
  const output = el(documentNode, "pre", "strategy-diff");
  output.hidden = true;
  const feedback = el(documentNode, "p", "strategy-action-feedback");
  feedback.setAttribute("aria-live", "polite");
  feedback.hidden = true;
  view.disabled = doc.revisions.length < 2;
  restore.disabled = doc.revisions.length < 2;
  const updateChange = () => {
    const fromRevision = doc.revisions.find(
      (row) => Number(row.revision) === Number(from.value),
    );
    const toRevision = doc.revisions.find(
      (row) => Number(row.revision) === Number(to.value),
    );
    if (
      Number.isFinite(Number(fromRevision?.line_count)) &&
      Number.isFinite(Number(toRevision?.line_count))
    ) {
      const lineDelta = Number(toRevision.line_count) -
        Number(fromRevision.line_count);
      const magnitude = Math.abs(lineDelta);
      change.textContent = `${lineDelta >= 0 ? "+" : "−"}${magnitude} ${
        magnitude === 1 ? "line" : "lines"
      }`;
      return;
    }
    const delta = Number(toRevision?.byte_length || 0) -
      Number(fromRevision?.byte_length || 0);
    change.textContent = `${delta >= 0 ? "+" : "−"}${formatBytes(
      Math.abs(delta),
    )}`;
  };
  from.addEventListener("change", () => {
    restore.textContent = `Restore revision ${from.value}…`;
    updateChange();
  });
  to.addEventListener("change", updateChange);
  updateChange();
  view.addEventListener("click", async () => {
    view.disabled = true;
    output.hidden = false;
    output.textContent = "Loading comparison…";
    try {
      const result = await callFunction(
        context.client,
        "strategy.revision.diff",
        {
          slug: doc.slug,
          from_revision: Number(from.value),
          to_revision: Number(to.value),
        },
        { kind: "global", project_id: String(projectId) },
      );
      const comparison = result.envelope.result?.comparison;
      output.textContent = comparison?.diff ||
        result.envelope.error?.message ||
        "No difference.";
      if (comparison?.diff) {
        const lines = String(comparison.diff).split(/\r?\n/);
        const additions = lines.filter(
          (line) => line.startsWith("+") && !line.startsWith("+++"),
        ).length;
        const removals = lines.filter(
          (line) => line.startsWith("-") && !line.startsWith("---"),
        ).length;
        change.textContent = `+${additions} / −${removals} lines`;
      }
    } catch (error) {
      output.textContent = `Comparison failed: ${String(error)}`;
    } finally {
      view.disabled = false;
    }
  });
  restore.addEventListener("click", async () => {
    const confirmed = typeof context.document.defaultView?.confirm !== "function" ||
      context.document.defaultView.confirm(
        `Restore revision ${from.value}? A new revision will be created.`,
      );
    if (!confirmed) return;
    restore.disabled = true;
    feedback.hidden = false;
    feedback.className = "strategy-action-feedback";
    feedback.textContent = `Restoring revision ${from.value}…`;
    try {
      const result = await callFunction(
        context.client,
        "strategy.revision.restore",
        {
          slug: doc.slug,
          revision: Number(from.value),
          base_updated_at: doc.updated_at,
        },
        { kind: "global", project_id: String(projectId) },
      );
      if (result.status === 200 && result.envelope.success) {
        feedback.textContent = "Revision restored.";
        refresh();
        return;
      }
      feedback.className += " error";
      feedback.textContent =
        result.envelope.error?.message || "Restore failed.";
    } catch (error) {
      feedback.className += " error";
      feedback.textContent = `Restore failed: ${String(error)}`;
    }
    restore.disabled = false;
  });
  actions.appendChild(view);
  actions.appendChild(restore);
  compare.body.appendChild(actions);
  compare.body.appendChild(el(
    documentNode,
    "p",
    "item-muted",
    `Restore creates revision ${Number(newest || 0) + 1}. History is never rewritten.`,
  ));
  compare.body.appendChild(feedback);
  compare.body.appendChild(output);
  split.appendChild(compare.panel);
  return split;
}
