// Per-actor needs-you surface: the gates on you, and messages sent to you.

import {
  callFunction,
  el,
  loadScopedPanels,
  section,
  withProjectColumn,
} from "./universe_view_support.js";
import {
  appendDecisionRow,
  appendActorMessageRow,
  appendPanelHint,
  appendRowError,
  createDecisionResolver,
  emptyRow,
} from "./inbox_rows.js";

export { inboxPresentation } from "./inbox_presentation.js";

function projectLabel(context, row) {
  const projects = typeof context.projects === "function"
    ? context.projects() : [];
  const rowLabel = row.project_slug || row.project;
  const rowKey = row.project_id ?? rowLabel;
  const project = projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value) === String(rowKey),
    )
  ));
  const label = rowLabel || project?.slug || project?.name || row.project_id;
  return label == null ? "" : String(label);
}

export function renderInboxView(context, main, scope) {
  const documentNode = context.document;
  const needs = section(
    documentNode, "Needs your decision", { showRaw: false },
  );
  const messages = section(documentNode, "Messages", { showRaw: false });
  appendPanelHint(documentNode, needs, "the gate waits until you resolve");
  for (const panel of [needs, messages]) {
    panel.children[1].className += " inbox-stack";
  }
  const host = el(documentNode, "div", "inbox-panels");
  host.appendChild(needs);
  host.appendChild(messages);
  main.replaceChildren(host);

  const rowColumns = withProjectColumn([
    { label: "subject", value: () => "" },
  ], scope, (row) => projectLabel(context, row));
  const projectColumn = rowColumns.find(
    (column) => column.label === "project",
  );
  const rowProject = (row) => projectColumn?.value(row) || null;
  const payload = scope === "all"
    ? {} : { project_ids: scope.map((value) => Number(value)) };
  const load = () => loadScopedPanels(context, [
    [needs, (body, calls) => {
      const rows = calls[0].envelope.result.needs_decision || [];
      needs.setCount(rows.length);
      if (!rows.length) {
        emptyRow(documentNode, body, "Nothing is waiting on you.");
      }
      for (const row of rows) {
        appendDecisionRow(context, body, row, resolve, rowProject(row));
      }
    }],
    [messages, (body, calls) => {
      const rows = calls[0].envelope.result.messages || [];
      messages.setCount(
        Number(calls[0].envelope.result.pending_actor_message_count || 0),
      );
      if (!rows.length) emptyRow(documentNode, body, "No unread messages.");
      for (const row of rows) {
        appendActorMessageRow(context, body, row, acknowledgeMessage);
      }
    }],
  ], [{ functionId: "inbox.list", payload }]);

  const resolve = createDecisionResolver(context, load);

  const acknowledgeMessage = async (messageId, button) => {
    button.disabled = true;
    let result;
    try {
      result = await callFunction(
        context.client,
        "session_control.message.acknowledge",
        { message_id: messageId },
      );
    } catch (error) {
      result = {
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      };
    }
    if (result.status === 200 && result.envelope.success) {
      await load();
      return;
    }
    button.disabled = false;
    appendRowError(
      documentNode,
      button.parentNode,
      result.envelope.error?.message || "The message could not be acknowledged.",
    );
  };

  load();
}
