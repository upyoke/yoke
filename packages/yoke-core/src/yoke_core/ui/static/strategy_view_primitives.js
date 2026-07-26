import {
  callFunction,
  el,
} from "./universe_view_support.js";
import {
  button,
  formatTimestamp,
  workflowPanel,
} from "./workflow_view_primitives.js";

function appendParagraph(documentNode, host, lines) {
  const text = lines.join(" ").trim();
  if (text) host.appendChild(el(documentNode, "p", null, text));
}

export function renderDocumentBody(documentNode, content) {
  const host = el(documentNode, "article", "strategy-document");
  const lines = String(content || "").split(/\r?\n/);
  let paragraph = [];
  let list = null;
  const flush = () => {
    appendParagraph(documentNode, host, paragraph);
    paragraph = [];
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trim();
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (heading) {
      flush();
      const level = Math.min(heading[1].length + 1, 4);
      host.appendChild(el(documentNode, `h${level}`, null, heading[2]));
    } else if (bullet) {
      appendParagraph(documentNode, host, paragraph);
      paragraph = [];
      if (!list) {
        list = el(documentNode, "ul");
        host.appendChild(list);
      }
      list.appendChild(el(documentNode, "li", null, bullet[1]));
    } else if (!line) {
      flush();
    } else {
      if (list) list = null;
      paragraph.push(line);
    }
  }
  flush();
  if (!host.children.length) {
    host.appendChild(el(documentNode, "p", "empty", "No content yet."));
  }
  return host;
}

export function documentReviewView(documentNode, doc) {
  const split = el(documentNode, "div", "strategy-split");
  const current = workflowPanel(
    documentNode,
    "Current document",
    {
      detail: [
        doc.current_revision ? `revision ${doc.current_revision}` : "unrevised",
        `${doc.bytes} B`,
        `updated ${formatTimestamp(doc.updated_at)}`,
      ].join(" · "),
    },
  );
  current.body.appendChild(renderDocumentBody(documentNode, doc.content));
  split.appendChild(current.panel);

  const harness = workflowPanel(documentNode, "Author through a harness");
  harness.body.className += " item-stack";
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
    "The web supports review, comments and approval; open-ended edits stay in the harness where the plan and repository can be understood together.",
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
  copy.appendChild(el(
    documentNode,
    "strong",
    null,
    `Revision ${revision.revision}${current ? " · current" : ""}`,
  ));
  copy.appendChild(el(
    documentNode,
    "span",
    "item-muted",
    [
      revision.source_operation,
      revision.session_id ? `session ${revision.session_id}` : null,
      `${revision.byte_length} B`,
      `${String(revision.content_sha256).slice(0, 8)}…`,
    ].filter(Boolean).join(" · "),
  ));
  row.appendChild(copy);
  row.appendChild(el(
    documentNode, "span", "item-muted", formatTimestamp(revision.created_at),
  ));
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
  view.disabled = doc.revisions.length < 2;
  restore.disabled = doc.revisions.length < 2;
  from.addEventListener("change", () => {
    restore.textContent = `Restore revision ${from.value}…`;
  });
  view.addEventListener("click", async () => {
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
    output.textContent = comparison?.diff || result.envelope.error?.message || "";
    output.hidden = false;
  });
  restore.addEventListener("click", async () => {
    const confirmed = typeof context.document.defaultView?.confirm !== "function" ||
      context.document.defaultView.confirm(
        `Restore revision ${from.value}? A new revision will be created.`,
      );
    if (!confirmed) return;
    restore.disabled = true;
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
    if (result.status === 200 && result.envelope.success) refresh();
    else restore.disabled = false;
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
  compare.body.appendChild(output);
  split.appendChild(compare.panel);
  return split;
}
