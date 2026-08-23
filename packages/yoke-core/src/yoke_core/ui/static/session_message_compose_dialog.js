import { el } from "./universe_view_support.js";
import {
  clearWorkflowDialog,
} from "./workflow_accessibility.js";
import { workflowDialogShell } from "./workflow_dialog_shell.js";
import {
  labelledControl,
  sessionControlCall,
  sessionControlIdempotencyKey,
  splitValues,
  statusRegion,
} from "./universe_session_control_data.js";

function recipientSelector(fields) {
  return {
    session_ids: splitValues(fields.sessions.value),
    item_refs: splitValues(fields.items.value),
    projects: splitValues(fields.projects.value),
    universe: Boolean(fields.universe.checked),
  };
}

function selectorHasAnchor(selector) {
  return selector.universe || selector.session_ids.length > 0
    || selector.item_refs.length > 0 || selector.projects.length > 0;
}

function renderRecipients(documentNode, host, recipients) {
  host.replaceChildren();
  if (!recipients.length) {
    host.appendChild(el(documentNode, "p", "sessions-empty", "No recipients resolved."));
    return;
  }
  const list = el(documentNode, "ul", "session-message-preview-list");
  for (const recipient of recipients) {
    const resolution = (recipient.resolution || []).join(", ") || "exact";
    list.appendChild(el(
      documentNode,
      "li",
      null,
      `${recipient.session_id} · ${recipient.project} · ${recipient.liveness} · ${resolution}`,
    ));
  }
  host.appendChild(list);
}

export function openSessionMessageCompose(context, host, {
  seedSessionIds = [], seedProjects = [], onSent = () => {},
} = {}) {
  const documentNode = context.document;
  const close = () => clearWorkflowDialog(host);
  const shell = workflowDialogShell(documentNode, host, "Message sessions", close);
  const fields = {
    sessions: el(documentNode, "textarea", "session-control-input"),
    items: el(documentNode, "input", "session-control-input"),
    projects: el(documentNode, "input", "session-control-input"),
    universe: el(documentNode, "input", "session-control-check"),
    body: el(documentNode, "textarea", "session-control-input session-message-body"),
  };
  fields.sessions.value = seedSessionIds.join("\n");
  fields.projects.value = seedProjects.join("\n");
  fields.universe.type = "checkbox";
  fields.body.setAttribute("rows", "8");
  fields.sessions.setAttribute("rows", "3");
  shell.dialog.appendChild(labelledControl(documentNode, "Session IDs", fields.sessions));
  shell.dialog.appendChild(labelledControl(documentNode, "Item references", fields.items));
  shell.dialog.appendChild(labelledControl(documentNode, "Projects", fields.projects));
  shell.dialog.appendChild(labelledControl(documentNode, "Universe broadcast", fields.universe));
  shell.dialog.appendChild(labelledControl(documentNode, "Operational message", fields.body));

  const status = statusRegion(documentNode);
  const recipients = el(documentNode, "div", "session-message-preview");
  const actions = el(documentNode, "div", "workflow-dialog-actions");
  const cancel = el(documentNode, "button", "workflow-button", "Cancel");
  const preview = el(documentNode, "button", "workflow-button", "Preview recipients");
  const send = el(documentNode, "button", "workflow-button primary", "Send message");
  for (const button of [cancel, preview, send]) button.type = "button";
  send.disabled = true;
  for (const button of [cancel, preview, send]) actions.appendChild(button);
  shell.dialog.appendChild(status);
  shell.dialog.appendChild(recipients);
  shell.dialog.appendChild(actions);

  let previewed = null;
  const idempotencyKey = sessionControlIdempotencyKey("workbench-message");
  const invalidate = () => {
    previewed = null;
    send.disabled = true;
    recipients.replaceChildren();
    status.hidden = true;
  };
  for (const field of Object.values(fields)) field.addEventListener("input", invalidate);
  cancel.addEventListener("click", shell.dismiss);
  preview.addEventListener("click", async () => {
    const selector = recipientSelector(fields);
    if (!selectorHasAnchor(selector) || !String(fields.body.value || "").trim()) {
      status.hidden = false;
      status.textContent = "Add at least one recipient anchor and a message.";
      return;
    }
    preview.disabled = true;
    status.hidden = false;
    status.textContent = "Resolving authorized recipients…";
    try {
      const result = await sessionControlCall(
        context, "session_control.message.preview", { selector },
      );
      previewed = {
        selector,
        body: String(fields.body.value),
        confirmationToken: result.confirmation_token || null,
      };
      renderRecipients(documentNode, recipients, result.recipients || []);
      status.textContent = `${result.recipient_count || 0} exact recipient(s) resolved.`;
      send.disabled = Number(result.recipient_count || 0) === 0;
    } catch (error) {
      status.textContent = String(error.message || error);
    } finally {
      preview.disabled = false;
    }
  });
  send.addEventListener("click", async () => {
    if (!previewed) return;
    send.disabled = true;
    status.hidden = false;
    status.textContent = "Sending to the confirmed recipient snapshot…";
    try {
      const result = await sessionControlCall(context, "session_control.message.send", {
        selector: previewed.selector,
        body: previewed.body,
        confirmation_token: previewed.confirmationToken,
        idempotency_key: idempotencyKey,
      });
      close();
      onSent(result);
    } catch (error) {
      status.textContent = String(error.message || error);
      send.disabled = false;
    }
  });
  shell.activate(fields.sessions);
}
