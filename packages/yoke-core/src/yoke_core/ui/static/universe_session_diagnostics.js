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

// Render the server projection without another browser-side classifier.
export function appendSessionPrimaryStatus(documentNode, host, row) {
  const state = row.session_state;
  const value = state?.presence === "present"
    ? state.activity : state?.presence || (sessionIsLive(row) ? "unavailable" : "ended");
  const pill = statePill(documentNode, value, value.replaceAll("_", " "));
  pill.className += " session-status-pill";
  host.appendChild(pill);
  const detail = [killExplanation(row), !state && sessionIsLive(row)
    ? "Session state unavailable; refresh after the server upgrade." : null]
    .filter(Boolean).join(" · ");
  const explanation = infoTooltip(documentNode, detail, `Why ${value}`);
  if (explanation) host.appendChild(explanation);
}

export function appendSessionStateFacts(documentNode, host, row) {
  const state = row.session_state;
  const facts = el(documentNode, "dl", "session-state-facts");
  const add = (label, value, className) => {
    const column = el(documentNode, "div", className);
    column.appendChild(el(documentNode, "dt", null, label));
    column.appendChild(el(documentNode, "dd", null, value));
    facts.appendChild(column);
  };
  add("Presence", state?.presence || "unavailable", "session-presence");
  add("Activity", (state?.activity || "unavailable").replaceAll("_", " "),
    "session-activity");
  const intent = state?.intent;
  add("Intent", [intent?.state || "unavailable", intent?.reason]
    .filter(Boolean).join(" · "), "session-intent");
  host.appendChild(facts);
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
