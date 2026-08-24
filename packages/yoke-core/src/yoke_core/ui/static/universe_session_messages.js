import { el } from "./universe_view_support.js";
import { pillFamilyForState } from "./universe_state_pills.js";
import { openSessionMessageCompose } from "./session_message_compose_dialog.js";
import { appendRelayDiagnostic } from "./session_relay_diagnostic_view.js";
import {
  formatSessionControlTime,
  presentSessionControlFailure,
  renderSessionControlFailure,
  scopedProjectRefs,
  sessionControlCall,
  statusRegion,
} from "./universe_session_control_data.js";

const MESSAGE_EXCERPT_CHARACTERS = 90;

function messageExcerpt(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "Message body unavailable";
  return text.length <= MESSAGE_EXCERPT_CHARACTERS
    ? text
    : `${text.slice(0, MESSAGE_EXCERPT_CHARACTERS - 1)}…`;
}

function messageState(message) {
  if (message.cancelled_at) return "cancelled";
  const states = new Set((message.recipients || []).map((row) => row.state));
  for (const state of ["pending", "injected", "acknowledged", "expired"]) {
    if (states.has(state)) return state;
  }
  return "pending";
}

function statePill(documentNode, state) {
  return el(
    documentNode, "span", `pill ${pillFamilyForState(state)}`, state,
  );
}

function receiptList(documentNode, message) {
  const list = el(documentNode, "ul", "session-message-receipts");
  for (const recipient of message.recipients || []) {
    const wakes = Number(recipient.wake_attempt_count || 0);
    let delivery = "waiting for a supported delivery hook";
    if (recipient.state === "acknowledged") {
      delivery = wakes
        ? `delivery acknowledged after ${wakes} wake attempt${wakes === 1 ? "" : "s"}`
        : "delivery acknowledged without a wake";
    } else if (recipient.state === "injected") {
      delivery = "injected; awaiting acknowledgement";
    } else if (recipient.state === "expired") {
      delivery = "delivery window expired";
    } else if (wakes) {
      delivery = `${wakes} wake attempt${wakes === 1 ? "" : "s"}`;
    } else if (recipient.wake_after) {
      delivery = `wake scheduled ${formatSessionControlTime(recipient.wake_after)}`;
    }
    list.appendChild(el(
      documentNode,
      "li",
      null,
      `${recipient.session_id} · ${recipient.state} · ${delivery}`,
    ));
    for (const attempt of message.attempts || []) {
      const target = String(attempt.target_session_id || "");
      if (target !== String(recipient.session_id || "")) {
        continue;
      }
      const detail = el(documentNode, "li", "session-message-attempt");
      if (appendRelayDiagnostic(
        documentNode, detail, attempt.evidence, recipient.machine_id,
      )) list.appendChild(detail);
    }
  }
  if (!list.children.length) {
    list.appendChild(el(
      documentNode, "li", null, `${message.recipient_count || 0} recipient(s)`,
    ));
  }
  return list;
}

function messageIdentityCell(documentNode, message) {
  const cell = el(documentNode, "td", "session-message-summary");
  cell.appendChild(el(
    documentNode, "strong", "session-message-excerpt", messageExcerpt(message.body),
  ));
  if (message.sender_session_id) {
    cell.appendChild(el(
      documentNode,
      "span",
      "session-message-sender",
      `From ${message.sender_session_id}`,
    ));
  }
  cell.appendChild(el(
    documentNode, "code", "session-control-id", String(message.message_id || "—"),
  ));
  return cell;
}

function appendMessageGuide(documentNode, host) {
  const guide = el(documentNode, "details", "session-control-guide");
  guide.appendChild(el(documentNode, "summary", null, "How Fleet messaging works"));
  const steps = el(documentNode, "ol");
  for (const step of [
    "Find a registered session in the roster and confirm it is Messageable.",
    "Compose the message and preview the exact recipients before sending.",
    "The recipient acts, then acknowledges; this page records delivery and wake attempts.",
  ]) steps.appendChild(el(documentNode, "li", null, step));
  guide.appendChild(steps);
  host.appendChild(guide);
}

function inProjectScope(message, projects) {
  if (projects === null) return true;
  const selected = new Set(projects.map(String));
  return (message.recipients || []).some(
    (recipient) => selected.has(String(recipient.project_id)),
  );
}

function renderMessages(documentNode, host, messages, cancelMessage) {
  host.replaceChildren();
  if (!messages.length) {
    host.appendChild(el(documentNode, "p", "sessions-empty", "No session messages yet."));
    return;
  }
  const table = el(documentNode, "table", "items session-control-table");
  table.appendChild(el(
    documentNode,
    "caption",
    "session-control-table-caption",
    "Message delivery and acknowledgement receipts",
  ));
  const tableHead = el(documentNode, "thead");
  const heading = el(documentNode, "tr");
  for (const label of ["Message", "State", "Receipts", "Created", "Action"]) {
    const header = el(documentNode, "th", null, label);
    header.setAttribute("scope", "col");
    heading.appendChild(header);
  }
  tableHead.appendChild(heading);
  table.appendChild(tableHead);
  const tableBody = el(documentNode, "tbody");
  for (const message of messages) {
    const row = el(documentNode, "tr");
    row.setAttribute("data-message-id", String(message.message_id || ""));
    row.appendChild(messageIdentityCell(documentNode, message));
    const stateCell = el(documentNode, "td");
    const state = messageState(message);
    stateCell.appendChild(statePill(documentNode, state));
    row.appendChild(stateCell);
    const receipt = el(documentNode, "td");
    receipt.appendChild(receiptList(documentNode, message));
    row.appendChild(receipt);
    row.appendChild(el(
      documentNode, "td", null, formatSessionControlTime(message.created_at),
    ));
    const action = el(documentNode, "td");
    const cancel = el(documentNode, "button", "item-button", "Cancel");
    cancel.type = "button";
    cancel.disabled = state === "cancelled" || state === "expired";
    cancel.setAttribute("aria-label", `Cancel message ${message.message_id}`);
    cancel.addEventListener("click", () => cancelMessage(message.message_id, cancel));
    action.appendChild(cancel);
    row.appendChild(action);
    tableBody.appendChild(row);
  }
  table.appendChild(tableBody);
  host.appendChild(table);
}

export function renderSessionMessagesView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const projects = scope === "all" ? null : scopedProjectRefs(context, scope);
  const view = el(documentNode, "div", "session-control-view");
  const status = statusRegion(documentNode);
  const content = el(documentNode, "div", "session-control-content", "Loading messages…");
  const dialogHost = el(documentNode, "div", "session-control-dialog-host");
  const compose = el(documentNode, "button", "item-button", "Compose message");
  compose.type = "button";
  const actions = el(documentNode, "div", "session-control-actions");
  actions.appendChild(compose);
  view.appendChild(actions);
  appendMessageGuide(documentNode, view);
  view.appendChild(status);
  view.appendChild(content);
  view.appendChild(dialogHost);
  main.replaceChildren(view);

  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({
      title: "Session messages",
      summary: "Confirmed recipients, durable delivery receipts, and cancellation.",
      actions: [compose],
    });
  }
  const load = async () => {
    try {
      const result = await sessionControlCall(
        context, "session_control.message.list", { limit: 100 },
      );
      if (!context.isMounted()) return;
      const messages = (result.messages || []).filter(
        (message) => inProjectScope(message, projects),
      );
      renderMessages(documentNode, content, messages, cancelMessage);
    } catch (error) {
      renderSessionControlFailure(
        content, error, "Session messages could not be loaded.",
      );
    }
  };
  const cancelMessage = async (messageId, button) => {
    button.disabled = true;
    status.hidden = false;
    status.textContent = `Cancelling ${messageId}…`;
    try {
      await sessionControlCall(context, "session_control.message.cancel", {
        message_id: messageId,
      });
      status.textContent = `${messageId} cancelled.`;
      await load();
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "The message could not be cancelled.",
      );
      button.disabled = false;
    }
  };
  compose.addEventListener("click", () => openSessionMessageCompose(
    context, dialogHost, { onSent: load },
  ));
  load();
}
