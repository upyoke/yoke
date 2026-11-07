import { attachTooltip, infoTooltip } from "./universe_tooltip.js";
import { relativeAge } from "./universe_time.js";
import { el, statePill } from "./universe_view_support.js";

// Presence and work ownership are independent, including for gone holders.
export function sessionIsLive(row) {
  return row.session_state?.presence
    ? row.session_state.presence !== "ended"
    : !row.ended_at && !row.terminated_at && row.liveness !== "ended";
}

const MESSAGE_STATES = new Set([
  "pending", "injected", "acknowledged", "cancelled", "expired",
]);

function latestMessageBadge(documentNode, message) {
  if (!message || !message.state) return null;
  const state = String(message.state).toLowerCase();
  const classState = MESSAGE_STATES.has(state) ? state : "unknown";
  const badge = el(
    documentNode,
    "span",
    `session-message-badge is-${classState}`,
    `${state} · ${relativeAge(message.created_at)}`,
  );
  attachTooltip(
    documentNode, badge, `Latest message ${message.message_id || ""}`.trim(),
  );
  return badge;
}

// The pill says what happened, not why: a termination reason is a sentence of
// operator prose, and rendering it inline turns a status marker into a red
// paragraph. The pill keeps the one-word state; this carries the reason and
// the fact that no recovery action exists, into the pill's explanation.
export function killExplanation(row) {
  if (row.ended_cause !== "killed") return "";
  const base = "Terminated: this session cannot be revived, woken, or messaged.";
  const reason = String(row.termination_reason || "").trim();
  return reason ? `${base} Reason: ${reason}` : base;
}

export const SESSION_STATUS_UPGRADE =
  "Session state unavailable; refresh after the server upgrade.";

export function sessionStatusAvailable(row) {
  const state = row.session_state;
  return ["working", "waiting", "ended"].includes(state?.status)
    && Object.hasOwn(state, "active_at") && typeof state.reason === "string";
}

// All card surfaces render the server's status, including during rollout.
export function appendSessionPrimaryStatus(documentNode, host, row) {
  const value = sessionStatusAvailable(row) ? row.session_state.status : "unavailable";
  const label = value[0].toUpperCase() + value.slice(1);
  const pill = statePill(documentNode, value, label);
  pill.className += " session-status-pill";
  host.appendChild(pill);
  if (value === "unavailable") attachTooltip(documentNode, pill, SESSION_STATUS_UPGRADE);
}

export function appendSessionHeaderDetails(documentNode, host, row) {
  const state = row.session_state;
  const intent = state?.intent;
  const next = state?.next_actor;
  const detail = [
    `Presence: ${state?.presence || "unavailable"}`,
    `Activity: ${state?.activity || "unavailable"}`,
    `Intent: ${intent?.state || "unavailable"}${intent?.reason ? ` · ${intent.reason}` : ""}`,
    `Next actor: ${next?.actor || "unavailable"}${next?.reason ? ` · ${next.reason}` : ""}`,
    ...[["Tool", row.last_tool_call_at], ["Prompt / stop", row.turn_posture_at],
      ["Finished turn", row.native_turn_end_recorded_at], ["Heartbeat", row.last_heartbeat]]
      .map(([name, time]) => `${name}: ${time || "unavailable"}`),
    killExplanation(row),
  ].filter(Boolean).join("\n");
  const info = infoTooltip(documentNode, detail, "Session details");
  info.classList.add("session-details");
  host.appendChild(info);
}

export function appendSessionChatTitle(documentNode, host, row) {
  if (row.chat_title) host.appendChild(el(
    documentNode, "div", "session-chat-title", row.chat_title,
  ));
}

export function appendSessionReason(documentNode, host, row) {
  host.appendChild(el(documentNode, "div", "session-reason",
    sessionStatusAvailable(row) ? row.session_state.reason : SESSION_STATUS_UPGRADE));
}

export function appendSessionMessageLine(
  documentNode, body, row, messageAction = null,
) {
  const badge = latestMessageBadge(documentNode, row.latest_message);
  if (badge || messageAction) {
    const message = el(documentNode, "div", "session-latest-message");
    if (messageAction) message.appendChild(messageAction);
    if (badge) {
      message.appendChild(el(
        documentNode, "span", "session-latest-label", "Latest:",
      ));
      message.appendChild(badge);
    }
    body.appendChild(message);
  }
}
