// Per-actor needs-you surface: governed decisions, requests, and notifications.

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
  appendNotificationRow,
  appendPanelHint,
  appendRowError,
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
  const requests = section(documentNode, "Requests", { showRaw: false });
  const notifications = section(
    documentNode, "Notifications", { showRaw: false },
  );
  const messages = section(documentNode, "Messages", { showRaw: false });
  appendPanelHint(documentNode, needs, "the gate waits until you resolve");
  appendPanelHint(documentNode, requests, "waiting, but nothing is halted");
  const markAll = el(
    documentNode, "button", "inbox-read inbox-read-all", "Mark all read",
  );
  markAll.type = "button";
  notifications.children[0].appendChild(markAll);
  for (const panel of [needs, requests, messages, notifications]) {
    panel.children[1].className += " inbox-stack";
  }
  const host = el(documentNode, "div", "inbox-panels");
  host.appendChild(needs);
  host.appendChild(requests);
  host.appendChild(messages);
  host.appendChild(notifications);
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
    [requests, (body, calls) => {
      const rows = calls[0].envelope.result.requests || [];
      requests.setCount(rows.length);
      if (!rows.length) emptyRow(documentNode, body, "No open requests.");
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
    [notifications, (body, calls) => {
      const rows = calls[0].envelope.result.notifications || [];
      notifications.setCount(rows.length);
      markAll.disabled = rows.length === 0;
      if (!rows.length) emptyRow(documentNode, body, "Nothing new.");
      for (const row of rows) {
        appendNotificationRow(context, body, row, readOne, rowProject(row));
      }
    }],
  ], [{ functionId: "inbox.list", payload }]);

  const resolve = async (row, action, wrap, note = null) => {
    const actionButtons = [];
    const collect = (node) => {
      if (node.classList?.contains("inbox-action")) actionButtons.push(node);
      for (const child of node.children || []) collect(child);
    };
    collect(wrap);
    for (const button of actionButtons) button.disabled = true;
    const resolution = { request_id: row.id, action };
    if (note) resolution.note = note;
    let result;
    try {
      result = await callFunction(
        context.client, "decision_requests.resolve", resolution,
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
    for (const button of actionButtons) button.disabled = false;
    appendRowError(
      documentNode,
      wrap,
      result.envelope.error?.message || "The decision could not be resolved.",
    );
  };

  const readOne = async (notificationId, button) => {
    button.disabled = true;
    let result;
    try {
      result = await callFunction(context.client, "notifications.read", {
        notification_id: notificationId,
      });
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
      result.envelope.error?.message ||
        "The notification could not be marked read.",
    );
  };

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

  markAll.addEventListener("click", async () => {
    markAll.disabled = true;
    const oldError = Array.from(notifications.children[1].children || []).find(
      (child) => child.classList?.contains("inbox-panel-error"),
    );
    if (oldError) notifications.children[1].removeChild(oldError);
    let result;
    try {
      result = await callFunction(
        context.client, "notifications.read_all", payload,
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
    markAll.disabled = false;
    const error = el(
      documentNode,
      "p",
      "inbox-panel-error error",
      result.envelope.error?.message ||
        "Notifications could not be marked read.",
    );
    error.setAttribute("role", "alert");
    notifications.children[1].appendChild(error);
  });
  load();
}
