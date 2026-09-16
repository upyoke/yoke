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

// The two delivery notices, named. Their kinds come from the inbox read,
// which classifies each message by the key that minted it — a reader must be
// able to tell a QA result from an item completing, and a retry of one from
// the other arriving.
export const NOTICE_LABELS = {
  qa_result: "QA result",
  delivery_done: "Item done",
};

export function appendActorMessageRow(context, body, message, acknowledge) {
  const documentNode = context.document;
  // A notice reports and asks nothing; a message from a person may ask. They
  // sit in different sections and the row says which it is, so the control
  // that clears it can say "dismiss" rather than promise an answer.
  const noticeLabel = NOTICE_LABELS[message.notice_kind];
  const wrap = el(
    documentNode, "article", `inbox-message${noticeLabel ? " is-notice" : ""}`,
  );
  wrap.setAttribute("data-message-id", String(message.message_id || ""));
  const main = el(documentNode, "div", "inbox-message-main");
  if (noticeLabel) {
    main.appendChild(el(
      documentNode, "div", "inbox-notice-kind", noticeLabel,
    ));
  }
  main.appendChild(el(
    documentNode,
    "div",
    "inbox-message-body",
    String(message.body || "Message body unavailable"),
  ));
  const link = el(documentNode, "a", "review-link", "Messages");
  link.href = "#/messages";
  main.appendChild(link);
  wrap.appendChild(main);
  // Who sent it and when, in a column of their own on the right. They used
  // to trail the body, so a long message pushed its own attribution off the
  // end of a paragraph and the acknowledgement after that.
  const aside = el(documentNode, "div", "inbox-message-sender");
  const meta = el(documentNode, "div", "inbox-message-meta");
  meta.appendChild(el(
    documentNode,
    "span",
    null,
    noticeLabel ? "Informational" : `From ${senderDescription(message)}`,
  ));
  if (message.created_at) meta.appendChild(relativeTime(documentNode, message.created_at));
  aside.appendChild(meta);
  if (message.actor_receipt?.state === "pending") {
    const button = el(
      documentNode, "button", "inbox-read", noticeLabel ? "Dismiss" : "Acknowledge",
    );
    button.type = "button";
    button.addEventListener("click", () => acknowledge(message.message_id, button));
    aside.appendChild(button);
  }
  wrap.appendChild(aside);
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
