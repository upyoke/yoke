import { el } from "./universe_view_support.js";
import { pillFamilyForState } from "./universe_state_pills.js";
import { appendRelayDiagnostic } from "./session_relay_diagnostic_view.js";
import {
  presentSessionControlFailure,
  renderSessionControlFailure,
  scopedProjectRefs,
  sessionControlCall,
  statusRegion,
} from "./universe_session_control_data.js";
import { relativeTime } from "./universe_time.js";
import {
  actorRecipientsOf,
  actorRecipientStateCounts,
  appendActorRecipientRows,
  senderMessageParty,
  sessionMessageParty,
} from "./universe_session_message_actors.js";

const OPEN_RECIPIENT_STATES = new Set(["pending", "injected"]);

function messageBody(value) {
  const text = String(value || "");
  return text || "Message body unavailable";
}

function recipientsOf(message) {
  return Array.isArray(message.recipients) ? message.recipients : [];
}

function deliverySummary(message) {
  if (message.cancelled_at) {
    return { state: "cancelled", label: "Cancelled", attention: false };
  }
  const counts = new Map();
  for (const recipient of recipientsOf(message)) {
    const state = String(recipient.state || "pending");
    counts.set(state, (counts.get(state) || 0) + 1);
  }
  for (const [state, count] of actorRecipientStateCounts(message)) {
    counts.set(state, (counts.get(state) || 0) + count);
  }
  const awaiting = (counts.get("pending") || 0) + (counts.get("injected") || 0);
  if (awaiting) {
    return {
      state: "pending",
      label: `${awaiting} awaiting`,
      attention: true,
    };
  }
  const acknowledged = counts.get("acknowledged") || 0;
  const expired = counts.get("expired") || 0;
  const cancelled = counts.get("cancelled") || 0;
  if (acknowledged && !expired) {
    return { state: "acknowledged", label: "Acknowledged", attention: false };
  }
  if (expired && !acknowledged) {
    return { state: "expired", label: "Expired", attention: false };
  }
  if (acknowledged || expired) {
    return {
      state: expired ? "expired" : "acknowledged",
      label: `${acknowledged} acknowledged · ${expired} expired`,
      attention: false,
    };
  }
  if (cancelled) {
    return { state: "cancelled", label: "Cancelled", attention: false };
  }
  return { state: "unknown", label: "Unknown delivery state", attention: false };
}

function statePill(documentNode, summary) {
  return el(
    documentNode,
    "span",
    `pill ${pillFamilyForState(summary.state)}`,
    summary.label,
  );
}

function appendRelativeStatus(documentNode, host, label, timestamp) {
  host.appendChild(el(documentNode, "span", null, timestamp ? `${label} ` : label));
  if (timestamp) host.appendChild(relativeTime(documentNode, timestamp));
}

function recipientStatus(documentNode, recipient, message) {
  const status = el(documentNode, "span", "session-message-recipient-status");
  const state = String(recipient.state || "pending");
  if (state === "acknowledged") {
    appendRelativeStatus(documentNode, status, "Acknowledged", recipient.acknowledged_at);
  } else if (state === "injected") {
    appendRelativeStatus(
      documentNode,
      status,
      "Awaiting acknowledgement",
      recipient.last_injected_at || recipient.created_at || message.created_at,
    );
  } else if (state === "expired") {
    appendRelativeStatus(documentNode, status, "Expired", recipient.expired_at);
  } else if (state === "cancelled") {
    appendRelativeStatus(
      documentNode, status, "Cancelled", recipient.cancelled_at || message.cancelled_at,
    );
  } else {
    appendRelativeStatus(
      documentNode,
      status,
      "Waiting for delivery",
      recipient.created_at || message.created_at,
    );
  }
  return status;
}

function deliveryMarker(documentNode, recipient) {
  const wakes = Number(recipient.wake_attempt_count || 0);
  if (!wakes && recipient.state !== "acknowledged") return null;
  const marker = el(
    documentNode,
    "span",
    `session-message-delivery-marker ${wakes ? "is-wake" : "is-direct"}`,
    wakes ? `Wake ×${wakes}` : "Direct",
  );
  marker.title = wakes
    ? `${wakes} wake attempt${wakes === 1 ? "" : "s"} ${
      recipient.state === "acknowledged"
        ? "preceded acknowledgement"
        : "made; acknowledgement is still pending"
    }`
    : "Acknowledged without a wake attempt";
  return marker;
}

function appendAttemptDiagnostics(documentNode, recipientNode, recipient, message) {
  for (const attempt of message.attempts || []) {
    if (String(attempt.target_session_id || "") !== String(recipient.session_id || "")) {
      continue;
    }
    appendRelayDiagnostic(
      documentNode, recipientNode, attempt.evidence, recipient.machine_id,
    );
  }
}

function recipientList(documentNode, message, sessions) {
  const list = el(documentNode, "ul", "session-message-recipients");
  for (const recipient of recipientsOf(message)) {
    const row = el(
      documentNode,
      "li",
      `session-message-recipient${OPEN_RECIPIENT_STATES.has(recipient.state) ? " is-waiting" : ""}`,
    );
    const main = el(documentNode, "div", "session-message-recipient-main");
    main.appendChild(sessionMessageParty(
      documentNode, recipient.session_id, recipient, sessions,
    ));
    main.appendChild(recipientStatus(documentNode, recipient, message));
    const marker = deliveryMarker(documentNode, recipient);
    if (marker) main.appendChild(marker);
    row.appendChild(main);
    appendAttemptDiagnostics(documentNode, row, recipient, message);
    list.appendChild(row);
  }
  appendActorRecipientRows(documentNode, list, message);
  return list;
}

function canCancel(message) {
  return !message.cancelled_at && (
    recipientsOf(message).some(
      (recipient) => OPEN_RECIPIENT_STATES.has(recipient.state),
    ) || actorRecipientsOf(message).some((recipient) => recipient.state === "pending")
  );
}

function messageRoute(documentNode, message, sessions) {
  const route = el(documentNode, "div", "session-message-route");
  const sender = el(documentNode, "span", "session-message-direction");
  sender.appendChild(el(documentNode, "span", null, "From "));
  sender.appendChild(senderMessageParty(documentNode, message));
  route.appendChild(sender);
  const count = recipientsOf(message).length + actorRecipientsOf(message).length
    || Number(message.recipient_count || 0);
  route.appendChild(el(
    documentNode,
    "span",
    "session-message-direction",
    `To ${count} recipient${count === 1 ? "" : "s"}`,
  ));
  const sent = el(documentNode, "span", "session-message-sent", "Sent ");
  sent.appendChild(relativeTime(documentNode, message.created_at));
  route.appendChild(sent);
  return route;
}

function messageCard(documentNode, message, sessions, cancelMessage, acknowledge) {
  const summary = deliverySummary(message);
  const card = el(
    documentNode,
    "li",
    `session-message-card${summary.attention ? " is-attention" : ""}`,
  );
  card.setAttribute("data-message-id", String(message.message_id || ""));
  card.setAttribute("data-message-state", summary.state);
  const header = el(documentNode, "div", "session-message-header");
  header.appendChild(statePill(documentNode, summary));
  if (canCancel(message)) {
    const cancel = el(documentNode, "button", "item-button", "Cancel");
    cancel.type = "button";
    cancel.setAttribute("aria-label", "Cancel message awaiting delivery");
    cancel.addEventListener("click", () => cancelMessage(message.message_id, cancel));
    header.appendChild(cancel);
  }
  if (message.actor_receipt?.state === "pending") {
    const read = el(documentNode, "button", "item-button primary", "Acknowledge");
    read.type = "button";
    read.setAttribute("aria-label", "Acknowledge message");
    read.addEventListener("click", () => acknowledge(message.message_id, read));
    header.appendChild(read);
  }
  card.appendChild(header);
  card.appendChild(el(
    documentNode, "p", "session-message-copy", messageBody(message.body),
  ));
  card.appendChild(messageRoute(documentNode, message, sessions));
  card.appendChild(recipientList(documentNode, message, sessions));
  return card;
}

function renderMessages(
  documentNode, host, messages, sessions, cancelMessage, acknowledge,
) {
  host.replaceChildren();
  if (!messages.length) {
    host.appendChild(el(
      documentNode,
      "p",
      "sessions-empty",
      "No session messages yet. Send from the Sessions roster.",
    ));
    return;
  }
  const list = el(documentNode, "ol", "session-message-list");
  for (const message of messages) {
    list.appendChild(messageCard(
      documentNode, message, sessions, cancelMessage, acknowledge,
    ));
  }
  host.appendChild(list);
}

function inProjectScope(message, projects) {
  if (projects === null) return true;
  if (actorRecipientsOf(message).length) return true;
  const selected = new Set(projects.map(String));
  return recipientsOf(message).some(
    (recipient) => selected.has(String(recipient.project_id)),
  );
}

export function renderSessionMessagesView(context, main, scope, chrome = {}) {
  const documentNode = context.document;
  const projects = scope === "all" ? null : scopedProjectRefs(context, scope);
  const view = el(documentNode, "div", "session-control-view");
  const status = statusRegion(documentNode);
  const pendingBadge = el(
    documentNode, "span", `pill ${pillFamilyForState("pending")}`, "0 pending",
  );
  const content = el(documentNode, "div", "session-control-content", "Loading messages…");
  view.appendChild(status);
  view.appendChild(pendingBadge);
  view.appendChild(content);
  main.replaceChildren(view);

  if (typeof chrome.setPageHead === "function") {
    chrome.setPageHead({
      title: "Session messages",
      summary: "What was sent, who is still waiting, and how each delivery arrived.",
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
      pendingBadge.textContent = `${messages.filter(
        (message) => message.actor_receipt?.state === "pending",
      ).length} pending`;
      let sessions = new Map();
      if (messages.length) {
        const roster = await sessionControlCall(
          context, "sessions.list", { limit: 500, per_project: true },
        );
        sessions = new Map((roster.rows || []).map(
          (row) => [String(row.session_id || ""), row],
        ));
      }
      if (!context.isMounted()) return;
      renderMessages(
        documentNode, content, messages, sessions, cancelMessage, acknowledge,
      );
    } catch (error) {
      renderSessionControlFailure(
        content, error, "Session messages could not be loaded.",
      );
    }
  };
  const cancelMessage = async (messageId, button) => {
    button.disabled = true;
    status.hidden = false;
    status.textContent = "Cancelling message…";
    try {
      await sessionControlCall(context, "session_control.message.cancel", {
        message_id: messageId,
      });
      status.textContent = "Message cancelled.";
      await load();
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "The message could not be cancelled.",
      );
      button.disabled = false;
    }
  };
  const acknowledge = async (messageId, button) => {
    button.disabled = true;
    status.hidden = false;
    status.textContent = "Acknowledging message…";
    try {
      await sessionControlCall(context, "session_control.message.acknowledge", {
        message_id: messageId,
      });
      status.textContent = "Message acknowledged.";
      await load();
    } catch (error) {
      status.textContent = presentSessionControlFailure(
        error, "The message could not be acknowledged.",
      );
      button.disabled = false;
    }
  };
  load();
}
