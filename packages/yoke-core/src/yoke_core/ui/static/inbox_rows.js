import { callFunction, el } from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
import { senderDescription } from "./universe_session_message_actors.js";

// Answering a gate is one act wherever its card is rendered — the Inbox,
// a deployment run card, the run page — so every caller resolves through
// this one function rather than repeating the disable/call/reload/report
// dance and drifting on what a failure says.
export function createDecisionResolver(context, reload) {
  const documentNode = context.document;
  return async (row, action, wrap, note = null) => {
    const actionButtons = [];
    // Every button in the card, not one surface's styling class: the same
    // resolver answers a gate drawn in the Inbox and one drawn inside a
    // deployment card, and both must go inert while the call is in flight.
    const collect = (node) => {
      if (node.tagName === "BUTTON") actionButtons.push(node);
      for (const child of node.children || []) collect(child);
    };
    collect(wrap);
    for (const button of actionButtons) button.disabled = true;
    const resolution = { request_id: row.id ?? row.request_id, action };
    if (note) resolution.note = note;
    let result;
    try {
      result = await callFunction(
        context.client, "decision_requests.resolve", resolution,
      );
    } catch (error) {
      result = {
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      };
    }
    if (result.status === 200 && result.envelope.success) {
      await reload();
      return;
    }
    for (const button of actionButtons) button.disabled = false;
    appendRowError(
      documentNode,
      wrap,
      result.envelope.error?.message || "The decision could not be resolved.",
    );
  };
}

export function appendActorMessageRow(context, body, message, acknowledge) {
  const documentNode = context.document;
  const wrap = el(documentNode, "article", "inbox-message");
  wrap.setAttribute("data-message-id", String(message.message_id || ""));
  const main = el(documentNode, "div", "inbox-message-main");
  main.appendChild(el(
    documentNode,
    "div",
    "inbox-message-body",
    String(message.body || "Message body unavailable"),
  ));
  const meta = el(documentNode, "div", "inbox-message-meta");
  meta.appendChild(el(documentNode, "span", null, `From ${senderDescription(message)}`));
  if (message.created_at) {
    meta.appendChild(el(documentNode, "span", null, " · "));
    meta.appendChild(relativeTime(documentNode, message.created_at));
  }
  meta.appendChild(el(documentNode, "span", null, " · "));
  const link = el(documentNode, "a", "review-link", "Messages");
  link.href = "#/messages";
  meta.appendChild(link);
  main.appendChild(meta);
  wrap.appendChild(main);
  if (message.actor_receipt?.state === "pending") {
    const button = el(documentNode, "button", "inbox-read", "Acknowledge");
    button.type = "button";
    button.addEventListener("click", () => acknowledge(message.message_id, button));
    wrap.appendChild(button);
  }
  body.appendChild(wrap);
}

export function emptyRow(documentNode, body, message) {
  body.appendChild(el(documentNode, "p", "empty inbox-empty", message));
}

export function appendRowError(documentNode, row, message) {
  const existing = Array.from(row.children || []).find(
    (child) => child.classList?.contains("inbox-row-error"),
  );
  if (existing) row.removeChild(existing);
  const error = el(
    documentNode,
    "p",
    "inbox-row-error error",
    message || "The action could not be completed.",
  );
  error.setAttribute("role", "alert");
  row.appendChild(error);
}
