import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";
import { pillFamilyForState } from "./universe_state_pills.js";
import { appendRelayDiagnostic } from "./session_relay_diagnostic_view.js";
import { presentSessionControlFailure } from "./universe_session_control_data.js";
import { relativeTime } from "./universe_time.js";
import {
  actorRecipientsOf,
  actorRecipientStateCounts,
  appendActorRecipientRows,
  senderMessageParty,
  sessionMessageParty,
} from "./universe_session_message_actors.js";

const OPEN_RECIPIENT_STATES = new Set(["pending", "injected"]);
const OPEN_STEERING_STATES = new Set(["awaiting_seat", "delivered"]);

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
  const steeringState = String(message.steering_recipient?.state || "");
  if (OPEN_STEERING_STATES.has(steeringState)) {
    counts.set("pending", (counts.get("pending") || 0) + 1);
  } else if (steeringState === "acknowledged") {
    counts.set("acknowledged", (counts.get("acknowledged") || 0) + 1);
  }
  const awaiting = (counts.get("pending") || 0) + (counts.get("injected") || 0);
  if (awaiting) {
    return { state: "pending", label: `${awaiting} awaiting`, attention: true };
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
  attachTooltip(documentNode, marker, wakes
    ? `${wakes} wake attempt${wakes === 1 ? "" : "s"} ${
      recipient.state === "acknowledged"
        ? "preceded acknowledgement"
        : "made; acknowledgement is still pending"
    }`
    : "Acknowledged without a wake attempt");
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

function recipientList(documentNode, message) {
  const list = el(documentNode, "ul", "session-message-recipients");
  for (const recipient of recipientsOf(message)) {
    const row = el(
      documentNode,
      "li",
      `session-message-recipient${OPEN_RECIPIENT_STATES.has(recipient.state) ? " is-waiting" : ""}`,
    );
    const main = el(documentNode, "div", "session-message-recipient-main");
    main.appendChild(sessionMessageParty(
      documentNode, recipient.session_id, recipient, new Map(),
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

function messageRoute(documentNode, message) {
  const route = el(documentNode, "div", "session-message-route");
  const sender = el(documentNode, "span", "session-message-direction");
  sender.appendChild(el(documentNode, "span", null, "From "));
  sender.appendChild(senderMessageParty(documentNode, message));
  route.appendChild(sender);
  const count = recipientsOf(message).length + actorRecipientsOf(message).length
    + (message.steering_recipient ? 1 : 0)
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

function appendExpansion(documentNode, card, messageId, view) {
  const region = el(documentNode, "div", "session-message-detail");
  const failure = view.detailFailures.get(messageId);
  const detail = view.details.get(messageId);
  if (failure) {
    region.appendChild(el(
      documentNode,
      "p",
      "error",
      presentSessionControlFailure(failure, "Message details could not be loaded."),
    ));
  } else if (!detail) {
    region.appendChild(el(documentNode, "p", null, "Loading details…"));
  } else {
    region.appendChild(recipientList(documentNode, detail));
  }
  card.appendChild(region);
}

export function messageCard(documentNode, message, view) {
  const summary = deliverySummary(message);
  const messageId = String(message.message_id || "");
  const card = el(
    documentNode,
    "li",
    `session-message-card${summary.attention ? " is-attention" : ""}`,
  );
  card.setAttribute("data-message-id", messageId);
  card.setAttribute("data-message-state", summary.state);
  const header = el(documentNode, "div", "session-message-header");
  header.appendChild(el(
    documentNode,
    "span",
    `pill ${pillFamilyForState(summary.state)}`,
    summary.label,
  ));
  if (canCancel(message)) {
    const cancel = el(documentNode, "button", "item-button", "Cancel");
    cancel.type = "button";
    cancel.setAttribute("aria-label", "Cancel message awaiting delivery");
    cancel.addEventListener("click", () => view.cancelMessage(messageId, cancel));
    header.appendChild(cancel);
  }
  if (message.actor_receipt?.state === "pending") {
    const read = el(documentNode, "button", "item-button primary", "Acknowledge");
    read.type = "button";
    read.setAttribute("aria-label", "Acknowledge message");
    read.addEventListener("click", () => view.acknowledge(messageId, read));
    header.appendChild(read);
  }
  card.appendChild(header);
  card.appendChild(el(
    documentNode, "p", "session-message-copy", messageBody(message.body),
  ));
  card.appendChild(messageRoute(documentNode, message));
  const expanded = view.expanded.has(messageId);
  const toggle = el(
    documentNode,
    "button",
    "item-button session-message-expand",
    expanded ? "Hide details" : "Details",
  );
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
  toggle.addEventListener("click", () => view.toggleDetail(messageId));
  card.appendChild(toggle);
  if (expanded) appendExpansion(documentNode, card, messageId, view);
  return card;
}
