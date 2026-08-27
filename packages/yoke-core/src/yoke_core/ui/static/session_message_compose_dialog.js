import { el } from "./universe_view_support.js";
import { clearWorkflowDialog } from "./workflow_accessibility.js";
import { workflowDialogShell } from "./workflow_dialog_shell.js";
import {
  labelledControl,
  presentSessionControlFailure,
  sessionControlCall,
  sessionControlIdempotencyKey,
  statusRegion,
} from "./universe_session_control_data.js";

export function exactSessionAudience(rows, filters = []) {
  const sessionIds = [...new Set((rows || []).map((row) => String(
    typeof row === "object" && row !== null ? row.session_id || "" : row || "",
  )).filter(Boolean))];
  return {
    sessionIds,
    filters: (filters || []).map((value) => String(value || "").trim()).filter(Boolean),
  };
}

function appendAudienceSummary(documentNode, dialog, audience) {
  const count = audience.sessionIds.length;
  const noun = count === 1 ? "session" : "sessions";
  dialog.appendChild(el(
    documentNode,
    "p",
    "session-control-help",
    `${count} ${noun} selected from the roster. The exact recipients resolve below.`,
  ));
  if (audience.filters.length) {
    dialog.appendChild(el(
      documentNode,
      "p",
      "session-message-filter-summary",
      `Filters: ${audience.filters.join(" · ")}`,
    ));
  }
}

function renderRecipients(documentNode, host, recipients) {
  host.replaceChildren();
  if (!recipients.length) {
    host.appendChild(el(
      documentNode,
      "p",
      "sessions-empty",
      "No sessions are in this audience. Close this dialog, refresh the roster, and choose the audience again.",
    ));
    return;
  }
  host.appendChild(el(
    documentNode,
    "p",
    "session-control-preview-heading",
    `Recipients (${recipients.length})`,
  ));
  const list = el(documentNode, "ul", "session-message-preview-list");
  for (const recipient of recipients) {
    const harness = recipient.executor_surface || recipient.executor || "harness unreported";
    const route = recipient.messageability?.messageable === false
      ? " · cannot receive messages"
      : "";
    list.appendChild(el(
      documentNode,
      "li",
      null,
      `${recipient.session_id} · ${recipient.project} · ${harness} · ${recipient.liveness}${route}`,
    ));
  }
  host.appendChild(list);
}

export function openSessionMessageCompose(context, host, {
  audience = exactSessionAudience([]), onSent = () => {},
} = {}) {
  const documentNode = context.document;
  const close = () => clearWorkflowDialog(host);
  const count = audience.sessionIds.length;
  const title = count === 1 ? "Message session" : `Message ${count} sessions`;
  const shell = workflowDialogShell(documentNode, host, title, close);
  appendAudienceSummary(documentNode, shell.dialog, audience);

  const body = el(documentNode, "textarea", "session-control-input session-message-body");
  body.setAttribute("rows", "8");
  body.placeholder = "What should the recipient do?";
  shell.dialog.appendChild(labelledControl(documentNode, "Operational message", body));

  const status = statusRegion(documentNode);
  const recipients = el(documentNode, "div", "session-message-preview");
  const actions = el(documentNode, "div", "workflow-dialog-actions");
  const cancel = el(documentNode, "button", "workflow-button", "Cancel");
  const send = el(documentNode, "button", "workflow-button primary", "Send message");
  for (const button of [cancel, send]) button.type = "button";
  send.disabled = true;
  actions.appendChild(cancel);
  actions.appendChild(send);
  shell.dialog.appendChild(status);
  shell.dialog.appendChild(recipients);
  shell.dialog.appendChild(actions);

  const selector = { session_ids: [...audience.sessionIds] };
  const idempotencyKey = sessionControlIdempotencyKey("workbench-message");
  let confirmed = null;
  let routeBlocked = true;
  const updateSend = () => {
    send.disabled = !confirmed || routeBlocked || !String(body.value || "").trim();
  };
  body.addEventListener("input", updateSend);
  cancel.addEventListener("click", shell.dismiss);
  send.addEventListener("click", async () => {
    if (!confirmed || send.disabled) return;
    send.disabled = true;
    status.hidden = false;
    status.textContent = "Sending to the shown recipients…";
    try {
      const result = await sessionControlCall(context, "session_control.message.send", {
        selector,
        body: String(body.value || "").trim(),
        confirmation_token: confirmed,
        idempotency_key: idempotencyKey,
      });
      close();
      onSent(result);
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "The message could not be sent.",
      );
      updateSend();
    }
  });

  const resolveAudience = async () => {
    status.hidden = false;
    if (!audience.sessionIds.length) {
      renderRecipients(documentNode, recipients, []);
      status.textContent = "Choose at least one roster session before composing a message.";
      return;
    }
    status.textContent = "Resolving the current roster audience…";
    try {
      const result = await sessionControlCall(
        context, "session_control.message.preview", { selector },
      );
      const exactRecipients = result.recipients || [];
      const unroutable = exactRecipients.filter(
        (recipient) => recipient.messageability?.messageable === false,
      );
      confirmed = String(result.confirmation_token || "").trim() || null;
      routeBlocked = !confirmed || exactRecipients.length === 0 || unroutable.length > 0;
      renderRecipients(documentNode, recipients, exactRecipients);
      const recipientLabel = exactRecipients.length === 1 ? "recipient" : "recipients";
      const blockedLabel = unroutable.length === 1 ? "session" : "sessions";
      status.textContent = unroutable.length
        ? `${exactRecipients.length} ${recipientLabel} selected; ${unroutable.length} ${blockedLabel} cannot receive Fleet messages. Adjust the roster audience before sending.`
        : !confirmed
          ? "The server did not confirm this audience. Close the dialog, refresh the roster, and choose it again."
          : `${exactRecipients.length} ${recipientLabel} ready.`;
      updateSend();
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "The roster audience could not be resolved.",
      );
    }
  };
  shell.activate(body);
  resolveAudience();
}
