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
  return { state: "pending", label: "Awaiting delivery", attention: true };
}

function statePill(documentNode, summary) {
  return el(
    documentNode,
    "span",
    `pill ${pillFamilyForState(summary.state)}`,
    summary.label,
  );
}

function itemHeldBy(session) {
  const claim = (session?.claims || []).find(
    (row) => row.target_kind === "item" && row.target === session.current_item,
  ) || (session?.claims || []).find((row) => row.target_kind === "item");
  return claim?.target || session?.current_item || "";
}

function sessionIdLabel(value) {
  const sessionId = String(value || "");
  return sessionId ? `session ${sessionId}` : "session not reported";
}

function sessionIdentity(documentNode, sessionId, snapshot, sessions) {
  const session = sessions.get(String(sessionId || ""));
  const surface = session?.executor_surface || session?.executor
    || snapshot?.executor_surface || snapshot?.executor;
  const work = itemHeldBy(session);
  const label = [surface, work].filter(Boolean).join(" · ")
    || sessionIdLabel(sessionId);
  const identity = el(documentNode, "span", "session-message-party", label);
  const title = [
    sessionId ? `Session ${sessionId}` : "",
    session?.current_item_title || "",
  ].filter(Boolean).join(" — ");
  if (title) identity.title = title;
  return identity;
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
    main.appendChild(sessionIdentity(
      documentNode, recipient.session_id, recipient, sessions,
    ));
    main.appendChild(recipientStatus(documentNode, recipient, message));
    const marker = deliveryMarker(documentNode, recipient);
    if (marker) main.appendChild(marker);
    row.appendChild(main);
    appendAttemptDiagnostics(documentNode, row, recipient, message);
    list.appendChild(row);
  }
  return list;
}

function canCancel(message) {
  return !message.cancelled_at && recipientsOf(message).some(
    (recipient) => OPEN_RECIPIENT_STATES.has(recipient.state),
  );
}

function messageRoute(documentNode, message, sessions) {
  const route = el(documentNode, "div", "session-message-route");
  const sender = el(documentNode, "span", "session-message-direction");
  sender.appendChild(el(documentNode, "span", null, "From "));
  sender.appendChild(sessionIdentity(
    documentNode, message.sender_session_id, null, sessions,
  ));
  route.appendChild(sender);
  const count = recipientsOf(message).length || Number(message.recipient_count || 0);
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

function messageCard(documentNode, message, sessions, cancelMessage) {
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
  card.appendChild(header);
  card.appendChild(el(
    documentNode, "p", "session-message-copy", messageBody(message.body),
  ));
  card.appendChild(messageRoute(documentNode, message, sessions));
  card.appendChild(recipientList(documentNode, message, sessions));
  return card;
}

function renderMessages(documentNode, host, messages, sessions, cancelMessage) {
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
  const ordered = [...messages].sort(
    (left, right) => Number(deliverySummary(right).attention)
      - Number(deliverySummary(left).attention),
  );
  for (const message of ordered) {
    list.appendChild(messageCard(documentNode, message, sessions, cancelMessage));
  }
  host.appendChild(list);
}

function inProjectScope(message, projects) {
  if (projects === null) return true;
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
  const content = el(documentNode, "div", "session-control-content", "Loading messages…");
  view.appendChild(status);
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
      renderMessages(documentNode, content, messages, sessions, cancelMessage);
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
  load();
}
