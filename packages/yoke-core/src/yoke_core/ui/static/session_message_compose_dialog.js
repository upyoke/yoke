import { el } from "./universe_view_support.js";
import {
  clearWorkflowDialog,
} from "./workflow_accessibility.js";
import { workflowDialogShell } from "./workflow_dialog_shell.js";
import {
  labelledControl,
  presentSessionControlFailure,
  sessionControlCall,
  sessionControlIdempotencyKey,
  splitValues,
  statusRegion,
} from "./universe_session_control_data.js";

const SELECTOR_FIELDS = [
  { key: "sessions", wire: "session_ids", label: "Session IDs", group: "anchor", example: "One ID per line" },
  { key: "items", wire: "item_refs", label: "Item references", group: "anchor", example: "For example, PROJECT-123" },
  { key: "epicTasks", wire: "epic_tasks", label: "Epic tasks (ITEM:TASK)", group: "advancedAnchor", example: "For example, PROJECT-123:4" },
  { key: "processes", wire: "process_keys", label: "Process keys", group: "advancedAnchor", example: "For example, release-coordination" },
  { key: "projects", wire: "projects", label: "Projects", group: "anchor", example: "For example, yoke" },
  { key: "executors", wire: "executor_families", label: "Executors", group: "filter" },
  { key: "surfaces", wire: "executor_surfaces", label: "Surfaces", group: "filter" },
  { key: "roles", wire: "work_roles", label: "Work roles", group: "filter" },
  { key: "executionLanes", wire: "execution_lanes", label: "Execution lanes", group: "filter" },
  { key: "worktrees", wire: "worktree_lanes", label: "Worktrees or branches", group: "filter" },
  { key: "machines", wire: "machine_ids", label: "Machine IDs", group: "filter" },
  { key: "liveness", wire: "liveness", label: "Liveness", group: "filter" },
  { key: "exclusions", wire: "exclude_session_ids", label: "Exclude session IDs", group: "exclude" },
];

function recipientSelector(fields) {
  const selector = { universe: Boolean(fields.universe.checked) };
  for (const field of SELECTOR_FIELDS) {
    selector[field.wire] = splitValues(fields[field.key].value);
  }
  return selector;
}

function selectorHasAnchor(selector) {
  return selector.universe || selector.session_ids.length > 0
    || selector.item_refs.length > 0 || selector.epic_tasks.length > 0
    || selector.process_keys.length > 0 || selector.projects.length > 0;
}

function selectorInput(documentNode, field) {
  const tag = field.key === "sessions" ? "textarea" : "input";
  const control = el(
    documentNode, tag,
    `session-control-input session-message-selector-${field.key}`,
  );
  if (tag === "textarea") control.setAttribute("rows", "3");
  control.placeholder = field.example || "Comma, space, or line separated";
  return control;
}

function appendSelectorGroup(documentNode, dialog, fields, group, heading) {
  dialog.appendChild(el(documentNode, "h3", "session-selector-heading", heading));
  for (const field of SELECTOR_FIELDS.filter((entry) => entry.group === group)) {
    dialog.appendChild(labelledControl(
      documentNode, field.label, fields[field.key],
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
      "No sessions matched. Check the IDs and filters, then preview again.",
    ));
    return;
  }
  host.appendChild(el(
    documentNode,
    "p",
    "session-control-preview-heading",
    `Exact recipients (${recipients.length})`,
  ));
  const list = el(documentNode, "ul", "session-message-preview-list");
  for (const recipient of recipients) {
    const resolution = (recipient.resolution || []).join(", ") || "exact";
    const route = recipient.messageability?.messageable === false
      ? " · not messageable"
      : "";
    list.appendChild(el(
      documentNode,
      "li",
      null,
      `${recipient.session_id} · ${recipient.project} · ${recipient.liveness} · matched by ${resolution}${route}`,
    ));
  }
  host.appendChild(list);
}

export function openSessionMessageCompose(context, host, {
  seedSessionId = null, onSent = () => {},
} = {}) {
  const documentNode = context.document;
  const close = () => clearWorkflowDialog(host);
  const shell = workflowDialogShell(documentNode, host, "Message sessions", close);
  const help = el(
    documentNode,
    "p",
    "session-control-help",
    "Choose recipients, preview the exact sessions, then send. Editing anything requires a new preview.",
  );
  help.id = "session-message-compose-help";
  shell.dialog.appendChild(help);
  const fields = {
    universe: el(
      documentNode, "input", "session-control-check session-message-selector-universe",
    ),
    body: el(documentNode, "textarea", "session-control-input session-message-body"),
  };
  for (const field of SELECTOR_FIELDS) {
    fields[field.key] = selectorInput(documentNode, field);
  }
  fields.sessions.value = seedSessionId ? String(seedSessionId) : "";
  fields.universe.type = "checkbox";
  fields.body.setAttribute("rows", "8");
  fields.body.placeholder = "What should the recipient do?";
  fields.sessions.setAttribute("aria-describedby", help.id);
  fields.body.setAttribute("aria-describedby", help.id);
  appendSelectorGroup(
    documentNode, shell.dialog, fields, "anchor", "Recipients",
  );
  shell.dialog.appendChild(labelledControl(
    documentNode,
    "Every visible session (exact preview required)",
    fields.universe,
  ));
  const advanced = el(documentNode, "details", "session-selector-advanced");
  advanced.appendChild(el(documentNode, "summary", null, "More targeting options"));
  appendSelectorGroup(
    documentNode, advanced, fields, "advancedAnchor", "Epic task and process anchors",
  );
  appendSelectorGroup(
    documentNode, advanced, fields, "filter", "Filters (match every filled field)",
  );
  appendSelectorGroup(documentNode, advanced, fields, "exclude", "Exclusions");
  shell.dialog.appendChild(advanced);
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
      status.textContent = "Choose at least one recipient and add a message before previewing.";
      return;
    }
    preview.disabled = true;
    status.hidden = false;
    status.textContent = "Resolving authorized recipients…";
    try {
      const result = await sessionControlCall(
        context, "session_control.message.preview", { selector },
      );
      const confirmationToken = String(result.confirmation_token || "").trim();
      previewed = confirmationToken ? {
        selector,
        body: String(fields.body.value),
        confirmationToken,
      } : null;
      const exactRecipients = result.recipients || [];
      const unroutable = exactRecipients.filter(
        (recipient) => recipient.messageability?.messageable === false,
      );
      const recipientLabel = exactRecipients.length === 1 ? "recipient" : "recipients";
      const blockedLabel = unroutable.length === 1 ? "session" : "sessions";
      renderRecipients(documentNode, recipients, exactRecipients);
      status.textContent = unroutable.length
        ? `${exactRecipients.length} exact ${recipientLabel} resolved; ${unroutable.length} ${blockedLabel} cannot receive Fleet messages. Choose a session marked Messageable in the roster.`
        : !confirmationToken
          ? "The server did not confirm this recipient snapshot. Preview again before sending."
          : `${result.recipient_count || 0} exact ${recipientLabel} resolved and confirmed.`;
      send.disabled = !confirmationToken || Number(result.recipient_count || 0) === 0
        || unroutable.length > 0;
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "Recipients could not be previewed.",
      );
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
      status.textContent = presentSessionControlFailure(
        error, "The message could not be sent.",
      );
      send.disabled = false;
    }
  });
  shell.activate(fields.sessions);
}
