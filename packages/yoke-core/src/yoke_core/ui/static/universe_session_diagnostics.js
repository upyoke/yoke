import { relativeAge } from "./universe_time.js";
import { el, statePill } from "./universe_view_support.js";

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
  badge.title = `Latest message ${message.message_id || ""}`.trim();
  return badge;
}

export function killCauseText(row) {
  if (row.ended_cause !== "killed") return "";
  const reason = String(row.termination_reason || "").trim();
  return reason ? `killed · ${reason}` : "killed";
}

// Past the staleness window: the session has been quiet long enough that the
// cleanup sweep would consider it, whether or not the roster has re-read its
// liveness since.
function pastStalenessWindow(row, now) {
  if (String(row.liveness || "") === "stale") return true;
  const eligible = new Date(row.stale_eligible_at).getTime();
  return !Number.isNaN(eligible) && eligible <= now;
}

function declaredWaitDetail(wait) {
  if (wait.kind === "dependency") {
    const status = String(wait.blocking_status || "").trim();
    const stage = status ? ` (${status})` : "";
    return `gated on ${wait.blocking_item}${stage}`;
  }
  return "turn parked for an answer";
}

// Health is what the session's own record says about its quiet, and the three
// answers are not degrees of one another. A session gated behind another item
// or holding its turn open is waiting by declaration and nothing is wrong with
// it. A session the stale-alive probe has already asked has a question
// outstanding, so its silence is being resolved. Only a quiet claim-holder
// with neither of those is a session nobody can account for — the one worth
// calling possibly stale.
export function sessionHealthState(row, now = Date.now()) {
  if (String(row.liveness || "") === "ended") return null;
  if (!(Array.isArray(row.claims) && row.claims.length)) return null;
  if (!pastStalenessWindow(row, now)) return null;
  const wait = row.declared_wait;
  if (wait) {
    return {
      state: "waiting",
      label: "waiting",
      detail: declaredWaitDetail(wait),
    };
  }
  const probe = row.stale_alive_probe;
  if (probe) {
    return {
      state: "probed",
      label: "probed",
      detail: `awaiting response · asked ${relativeAge(probe.created_at)}`,
    };
  }
  return {
    state: "stale",
    label: "possibly stale",
    detail: "quiet past the staleness window with claims still held",
  };
}

// A killed session is ended like any other gone session; the kill is a cause
// of death, so it reads as a badge on ended rather than a liveness state.
function appendKillCause(documentNode, body, row) {
  const text = killCauseText(row);
  if (!text) return;
  const line = el(documentNode, "div", "session-ended-cause");
  const badge = el(documentNode, "span", "session-kill-badge", text);
  badge.title = "Terminated: this session cannot be revived, woken, or messaged.";
  line.appendChild(badge);
  const at = relativeAge(row.terminated_at);
  if (at) line.appendChild(el(documentNode, "span", "session-kill-when", at));
  body.appendChild(line);
}

function appendHealth(documentNode, body, row) {
  const health = sessionHealthState(row);
  if (!health) return;
  const line = el(documentNode, "div", "session-health");
  const pill = statePill(documentNode, health.state, health.label);
  pill.className = `${pill.className} session-health-pill`;
  line.appendChild(pill);
  line.appendChild(el(
    documentNode, "span", "session-health-detail", health.detail,
  ));
  body.appendChild(line);
}

export function appendSessionDiagnostics(documentNode, body, row) {
  appendKillCause(documentNode, body, row);
  const badge = latestMessageBadge(documentNode, row.latest_message);
  if (badge) {
    const message = el(documentNode, "div", "session-latest-message");
    message.appendChild(el(documentNode, "span", null, "Latest message"));
    message.appendChild(badge);
    body.appendChild(message);
  }
  appendHealth(documentNode, body, row);
}
