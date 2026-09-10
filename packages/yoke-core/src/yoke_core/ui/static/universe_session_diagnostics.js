import { attachTooltip, infoTooltip } from "./universe_tooltip.js";
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

// Past the staleness window: the session has been quiet long enough that the
// cleanup sweep would consider it, whether or not the roster has re-read its
// liveness since.
function pastStalenessWindow(row, now) {
  if (String(row.liveness || "") === "stale") return true;
  const eligible = new Date(row.stale_eligible_at).getTime();
  return !Number.isNaN(eligible) && eligible <= now;
}

// A declared wait is a state, not a footnote to one. Gating behind another
// item and holding the turn open for an answer are different situations with
// different answers, so each names itself in the pill and explains itself in
// the pill's tooltip.
function declaredWaitStatus(wait) {
  if (wait.kind === "dependency") {
    const status = String(wait.blocking_status || "").trim();
    const stage = status ? ` (${status})` : "";
    return {
      state: "waiting",
      label: "waiting",
      detail: `gated on ${wait.blocking_item}${stage}`,
    };
  }
  return {
    state: "parked",
    label: "parked",
    detail: "turn parked for an answer",
  };
}

// A session that stamped `parked` about itself is accounted for in exactly
// the way a declared wait is, so it reads as the same state rather than as a
// second badge beside whatever the liveness read happened to say.
function selfParkedStatus(row) {
  if (String(row.mode || "").toLowerCase() !== "parked") return null;
  return {
    state: "parked",
    label: "parked",
    detail: "parked by the session itself; its next tool call takes it back",
  };
}

// Health is what the session's own record says about its quiet, and the three
// answers are not degrees of one another. A session gated behind another item
// or holding its turn open is waiting by declaration and nothing is wrong with
// it. A session the stale-alive probe has already asked has a question
// outstanding, so its silence is being resolved. A quiet claim-holder with
// neither of those is unaccounted for: confirmed stale when the server already
// says so, possibly stale only while it is still classified active.
export function sessionHealthState(row, now = Date.now()) {
  if (String(row.liveness || "") === "ended") return null;
  const holdings = row.holdings && Array.isArray(row.holdings.current)
    ? row.holdings.current : [];
  if (!(holdings.length || (Array.isArray(row.claims) && row.claims.length))) {
    return null;
  }
  if (row.native_process && row.native_process.state === "gone") {
    return {
      state: "process-gone",
      label: "process gone",
      detail: "claims held — terminate deliberately if dead",
    };
  }
  if (!pastStalenessWindow(row, now)) return null;
  const wait = row.declared_wait;
  if (wait) return declaredWaitStatus(wait);
  const probe = row.stale_alive_probe;
  if (probe) {
    return {
      state: "probed",
      label: "probed",
      detail: `awaiting response · asked ${relativeAge(probe.created_at)}`,
    };
  }
  const detail = "quiet past the staleness window with claims still held";
  // Server-stale is confirmed. "Possibly stale" is only the still-active
  // holder whose roster has not yet re-read liveness — never both.
  if (String(row.liveness || "") === "stale") {
    return { state: "stale", label: "stale", detail };
  }
  return { state: "possibly stale", label: "possibly stale", detail };
}

/**
 * The one state the card shows, whichever state actually applies.
 *
 * A card used to be able to say three things about one silence at once — a
 * `waiting` pill, a `parked` pill beside it, and a sentence underneath that
 * repeated whichever of them was right. The reasons and recovery actions all
 * survived that collapse by moving into `detail`, which the pill's own
 * explanation renders; what did not survive is the second badge.
 *
 * A self-declared park is checked before the quiet reads for the same reason
 * a declared wait is: the session has already accounted for its own silence,
 * so reporting it as possibly stale would describe a session nobody is
 * missing.
 */
export function sessionPrimaryStatus(row, now = Date.now()) {
  const liveness = String(row.liveness || "").toLowerCase();
  const killed = killExplanation(row);
  const carrying = (status) => (killed
    ? { ...status, detail: [status.detail, killed].filter(Boolean).join(" · ") }
    : status);
  if (liveness === "ended") {
    return carrying({ state: "ended", label: "ended", detail: null });
  }
  const health = sessionHealthState(row, now);
  if (health && health.state === "process-gone") return carrying(health);
  const parked = selfParkedStatus(row);
  if (parked) return carrying(parked);
  if (health) return carrying(health);
  if (liveness === "stale") {
    return carrying({ state: "stale", label: "stale", detail: null });
  }
  // Recency lives on the timing line as "active now" / "idle Xm"; the
  // identity pill says only that the session is live.
  if (liveness === "active") {
    return carrying({ state: "active", label: "active", detail: null });
  }
  return carrying({ state: "unknown", label: "unknown", detail: null });
}

/**
 * Everything the card knows about why this session reads the way it does.
 *
 * The state's own detail and the session's recorded quiet reason are two
 * halves of one answer, and a session that recorded the same sentence its
 * state already implies says it once.
 */
export function sessionStatusExplanation(row, now = Date.now()) {
  const status = sessionPrimaryStatus(row, now);
  const quiet = String(row.quiet_reason ?? "").trim();
  const parts = [status.detail, quiet].filter(Boolean);
  return [...new Set(parts)].join(" · ");
}

/**
 * The status pill, and — only where there is more to know — the (i) that
 * carries the rest of it on hover, tap and focus.
 */
export function appendSessionPrimaryStatus(documentNode, host, row, now = Date.now()) {
  const status = sessionPrimaryStatus(row, now);
  const pill = statePill(documentNode, status.state, status.label);
  const confirmed = status.state === "stale" ? " session-stale-pill" : "";
  pill.className = `${pill.className} session-status-pill${confirmed}`;
  host.appendChild(pill);
  const explanation = infoTooltip(
    documentNode, sessionStatusExplanation(row, now), `Why ${status.label}`,
  );
  if (explanation) host.appendChild(explanation);
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
