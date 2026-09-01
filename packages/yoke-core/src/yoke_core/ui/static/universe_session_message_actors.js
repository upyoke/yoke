import { el } from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";

export function actorRecipientsOf(message) {
  return Array.isArray(message.actor_recipients) ? message.actor_recipients : [];
}

export function senderDescription(message) {
  const label = String(
    message.sender_actor_label || `actor ${message.sender_actor_id || "unknown"}`,
  );
  if (message.sender_session_id) {
    return `${label} via session ${message.sender_session_id}`;
  }
  const kind = String(message.sender_actor_kind || "actor");
  const surface = String(
    message.sender_surface_label || message.sender_surface || "unknown surface",
  );
  return `${label} (${kind}, ${surface})`;
}

function itemHeldBy(session) {
  const claim = (session?.claims || []).find(
    (row) => row.target_kind === "item" && row.target === session.current_item,
  ) || (session?.claims || []).find((row) => row.target_kind === "item");
  return claim?.target || session?.current_item || "";
}

export function sessionMessageParty(documentNode, sessionId, snapshot, sessions) {
  const session = sessions.get(String(sessionId || ""));
  const surface = session?.executor_surface || session?.executor
    || snapshot?.executor_surface || snapshot?.executor;
  const work = itemHeldBy(session);
  const label = [surface, work].filter(Boolean).join(" · ")
    || (sessionId ? `session ${sessionId}` : "session not reported");
  const identity = el(documentNode, "span", "session-message-party", label);
  const title = [
    sessionId ? `Session ${sessionId}` : "",
    session?.current_item_title || "",
  ].filter(Boolean).join(" — ");
  if (title) identity.title = title;
  return identity;
}

export function senderMessageParty(documentNode, message) {
  return el(
    documentNode, "span", "session-message-party", senderDescription(message),
  );
}

function actorStatus(documentNode, recipient, message) {
  const status = el(documentNode, "span", "session-message-recipient-status");
  const state = String(recipient.state || "pending");
  const timestamp = state === "read"
    ? recipient.read_at
    : state === "expired"
      ? recipient.expired_at
      : recipient.created_at || message.created_at;
  const label = state === "read"
    ? "Read"
    : state === "expired"
      ? "Expired"
      : "Waiting to be read";
  status.appendChild(el(documentNode, "span", null, timestamp ? `${label} ` : label));
  if (timestamp) status.appendChild(relativeTime(documentNode, timestamp));
  return status;
}

export function appendActorRecipientRows(documentNode, list, message) {
  for (const recipient of actorRecipientsOf(message)) {
    const waiting = String(recipient.state || "pending") === "pending";
    const row = el(
      documentNode,
      "li",
      `session-message-recipient${waiting ? " is-waiting" : ""}`,
    );
    const main = el(documentNode, "div", "session-message-recipient-main");
    main.appendChild(el(
      documentNode,
      "span",
      "session-message-party",
      recipient.label || `actor ${recipient.actor_id}`,
    ));
    main.appendChild(actorStatus(documentNode, recipient, message));
    const marker = el(
      documentNode,
      "span",
      "session-message-delivery-marker is-direct",
      "Human",
    );
    marker.title = "Durable human inbox recipient";
    main.appendChild(marker);
    row.appendChild(main);
    list.appendChild(row);
  }
}

export function actorRecipientStateCounts(message) {
  const counts = new Map();
  for (const recipient of actorRecipientsOf(message)) {
    const state = recipient.state === "read" ? "acknowledged" : recipient.state;
    counts.set(state, (counts.get(state) || 0) + 1);
  }
  return counts;
}
