import { relativeAge } from "./universe_time.js";
import { el } from "./universe_view_support.js";

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

export function endBlockerText(blocker) {
  if (!blocker) return "";
  if (blocker.status === "has_claims") {
    const count = Number(blocker.active_claim_count) || 0;
    return `${count} work claim${count === 1 ? "" : "s"} held`;
  }
  if (blocker.status === "has_document_locks") {
    const count = Number(blocker.active_document_lock_count) || 0;
    return `${count} document lock${count === 1 ? "" : "s"} held`;
  }
  if (blocker.status === "chain_pending") {
    return `chain pending (step ${blocker.checkpoint_step}/${blocker.max_chain_steps})`;
  }
  return String(blocker.status || "end blocked").replaceAll("_", " ");
}

export function staleEligibilityText(row, now = Date.now()) {
  const eligible = new Date(row.stale_eligible_at).getTime();
  if (Number.isNaN(eligible)) return "";
  const minutes = Math.max(0, Math.ceil((eligible - now) / 60000));
  return minutes === 0 ? "stale-eligible now" : `stale-eligible in ${minutes}m`;
}

export function appendSessionDiagnostics(documentNode, body, row) {
  const badge = latestMessageBadge(documentNode, row.latest_message);
  if (badge) {
    const message = el(documentNode, "div", "session-latest-message");
    message.appendChild(el(documentNode, "span", null, "Latest message"));
    message.appendChild(badge);
    body.appendChild(message);
  }
  const blocker = endBlockerText(row.end_blocker);
  if (blocker) {
    body.appendChild(el(
      documentNode,
      "p",
      "fact-line session-end-blocker",
      `Why active: ${blocker}`,
    ));
  }
  const stale = staleEligibilityText(row);
  if (stale && row.liveness !== "ended" && row.liveness !== "terminated") {
    const line = el(
      documentNode,
      "p",
      "fact-line session-stale-context",
      `Stale cleanup: ${stale}`,
    );
    if (row.effective_stale_ttl_minutes != null) {
      line.title = `Effective stale TTL: ${row.effective_stale_ttl_minutes}m`;
    }
    body.appendChild(line);
  }
}
