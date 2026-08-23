import { el } from "./universe_view_support.js";
import { pillFamilyForState } from "./universe_state_pills.js";
import { openSessionMessageCompose } from "./session_message_compose_dialog.js";
import {
  presentSessionControlFailure,
  renderSessionControlFailure,
  scopedProjectRefs,
  sessionControlCall,
  statusRegion,
} from "./universe_session_control_data.js";

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
      delivery = `wake scheduled ${recipient.wake_after}`;
    }
    list.appendChild(el(
      documentNode,
      "li",
      null,
      `${recipient.session_id} · ${recipient.state} · ${delivery}`,
    ));
  }
  if (!list.children.length) {
    list.appendChild(el(
      documentNode, "li", null, `${message.recipient_count || 0} recipient(s)`,
    ));
  }
  return list;
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
  const heading = el(documentNode, "tr");
  for (const label of ["Message", "State", "Receipts", "Created", "Action"]) {
    heading.appendChild(el(documentNode, "th", null, label));
  }
  table.appendChild(heading);
  for (const message of messages) {
    const row = el(documentNode, "tr");
    row.appendChild(el(documentNode, "td", "session-control-id", message.message_id));
    const stateCell = el(documentNode, "td");
    const state = messageState(message);
    stateCell.appendChild(statePill(documentNode, state));
    row.appendChild(stateCell);
    const receipt = el(documentNode, "td");
    receipt.appendChild(receiptList(documentNode, message));
    row.appendChild(receipt);
    row.appendChild(el(documentNode, "td", null, String(message.created_at || "")));
    const action = el(documentNode, "td");
    const cancel = el(documentNode, "button", "item-button", "Cancel");
    cancel.type = "button";
    cancel.disabled = state === "cancelled" || state === "expired";
    cancel.addEventListener("click", () => cancelMessage(message.message_id, cancel));
    action.appendChild(cancel);
    row.appendChild(action);
    table.appendChild(row);
  }
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
