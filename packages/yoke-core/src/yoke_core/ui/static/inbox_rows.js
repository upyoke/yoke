import { callFunction, el } from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
import {
  ACTION_LABELS,
  ACTION_RANK,
  decisionLinks,
  decisionSubtitle,
  decisionTitle,
  KIND_PRESENTATION,
  yourDecisionText,
} from "./inbox_presentation.js";
import { appendGateBody } from "./decision_gate_body.js";
import { senderDescription } from "./universe_session_message_actors.js";

// The named destinations, and the only navigation in the row. The whole tile
// used to be one link, so a reader could not select a word of the decision
// they were being asked to make -- not the item ref, not a run id, not the
// reason an agent gave for not deciding. Text is text; identifiers are links.
function appendLinks(documentNode, host, links) {
  if (!links.length) return null;
  const row = el(documentNode, "div", "inbox-row-links");
  for (const link of links) {
    const anchor = el(documentNode, "a", "inbox-row-link", link.label);
    anchor.href = link.href;
    row.appendChild(anchor);
  }
  host.appendChild(row);
  return row;
}

function timedSubtitle(
  documentNode,
  text,
  createdAt,
  verb = "",
  trailingText = "",
  projectLabel = null,
) {
  const subtitle = el(documentNode, "div", "inbox-row-subtitle");
  if (projectLabel) {
    subtitle.appendChild(el(
      documentNode, "span", "inbox-row-project", projectLabel,
    ));
  }
  if (projectLabel && (text || createdAt || trailingText)) {
    subtitle.appendChild(el(documentNode, "span", null, " · "));
  }
  if (text) subtitle.appendChild(el(documentNode, "span", null, text));
  if (createdAt) {
    if (text) subtitle.appendChild(el(documentNode, "span", null, " · "));
    if (verb) subtitle.appendChild(el(documentNode, "span", null, `${verb} `));
    subtitle.appendChild(relativeTime(documentNode, createdAt));
  }
  if (trailingText) {
    if (text || createdAt) {
      subtitle.appendChild(el(documentNode, "span", null, " · "));
    }
    subtitle.appendChild(el(documentNode, "span", null, trailingText));
  }
  return subtitle;
}

export function appendPanelHint(documentNode, panel, text) {
  panel.children[0].appendChild(el(
    documentNode, "span", "inbox-panel-hint", text,
  ));
}

export function appendDecisionRow(
  context,
  body,
  row,
  invoke,
  projectLabel = null,
) {
  const documentNode = context.document;
  const wrap = el(documentNode, "article", "inbox-row");
  wrap.setAttribute("data-request-id", row.id);
  const presentation = KIND_PRESENTATION[row.kind] || { icon: "•" };
  wrap.appendChild(el(documentNode, "span", "inbox-icon", presentation.icon));
  const main = el(documentNode, "div", "inbox-row-main");
  main.appendChild(el(
    documentNode, "div", "inbox-row-title", decisionTitle(row),
  ));
  const subtitle = decisionSubtitle(row);
  main.appendChild(timedSubtitle(
    documentNode,
    subtitle.leading,
    row.created_at,
    subtitle.timeVerb,
    subtitle.trailing,
    projectLabel,
  ));
  appendLinks(documentNode, main, decisionLinks(row));
  wrap.appendChild(main);
  // The body goes in before the actions so a gate that shows evidence reads
  // top to bottom -- what it is, what you are approving, then the answer.
  // A kind with nothing to show (a machine, answered on the Machines page)
  // stays the one-line row it already was.
  if (appendGateBody(context, wrap, row)) {
    wrap.className += " inbox-row-gate";
  }
  const actions = el(documentNode, "div", "inbox-actions");
  if (row.decided_by_you) {
    // A decision is final for the person who made it; under an all-approvers
    // policy the gate stays open for everyone else, so this row reports their
    // own answer rather than offering an action they cannot take again.
    actions.appendChild(el(
      documentNode, "span", "inbox-decided", yourDecisionText(row),
    ));
    wrap.appendChild(actions);
    body.appendChild(wrap);
    return;
  }
  const orderedActions = [...(row.actions || [])].sort(
    (left, right) => Number(ACTION_RANK[left] ?? 1) -
      Number(ACTION_RANK[right] ?? 1),
  );
  for (const action of orderedActions) {
    const button = el(
      documentNode, "button",
      `item-button inbox-action${action === "approve" ? " primary" : ""}`,
      ACTION_LABELS[action] || action,
    );
    button.type = "button";
    button.setAttribute("data-action", action);
    button.addEventListener("click", () => {
      if (action !== "request_changes") {
        invoke(row, action, wrap);
        return;
      }
      if (Array.from(wrap.children).some(
        (child) => child.classList.contains("inbox-note-composer"),
      )) return;
      const composer = el(documentNode, "div", "inbox-note-composer");
      const note = el(
        documentNode, "textarea", "item-form-control inbox-note",
      );
      note.setAttribute("aria-label", "Change request note");
      note.setAttribute("placeholder", "What needs to change?");
      composer.appendChild(note);
      const cancel = el(
        documentNode, "button", "item-button inbox-action", "Cancel",
      );
      cancel.type = "button";
      cancel.addEventListener("click", () => wrap.removeChild(composer));
      composer.appendChild(cancel);
      const send = el(
        documentNode,
        "button",
        "item-button inbox-action primary",
        "Request changes",
      );
      send.type = "button";
      send.addEventListener("click", () => {
        if (!String(note.value || "").trim()) {
          note.classList.add("invalid");
          return;
        }
        invoke(row, action, wrap, String(note.value).trim());
      });
      composer.appendChild(send);
      wrap.appendChild(composer);
    });
    actions.appendChild(button);
  }
  wrap.appendChild(actions);
  body.appendChild(wrap);
}

// Answering a gate is one act wherever its row is rendered — the Inbox
// panel, the Machines page — so every caller resolves through this one
// function rather than repeating the disable/call/reload/report dance and
// drifting on what a failure says.
export function createDecisionResolver(context, reload) {
  const documentNode = context.document;
  return async (row, action, wrap, note = null) => {
    const actionButtons = [];
    // Every button in the row, not one surface's styling class: the same
    // resolver answers a gate drawn as an Inbox row and one drawn inside a
    // deployment card, and both must go inert while the call is in flight.
    const collect = (node) => {
      if (node.tagName === "BUTTON") actionButtons.push(node);
      for (const child of node.children || []) collect(child);
    };
    collect(wrap);
    for (const button of actionButtons) button.disabled = true;
    const resolution = { request_id: row.id, action };
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
  const wrap = el(documentNode, "article", "inbox-row inbox-message-row");
  wrap.setAttribute("data-message-id", String(message.message_id || ""));
  wrap.appendChild(el(documentNode, "span", "inbox-icon", "✉"));
  const main = el(documentNode, "div", "inbox-row-main");
  main.appendChild(el(
    documentNode,
    "div",
    "inbox-row-title",
    String(message.body || "Message body unavailable"),
  ));
  main.appendChild(timedSubtitle(
    documentNode,
    `From ${senderDescription(message)}`,
    message.created_at,
  ));
  appendLinks(documentNode, main, [{ label: "Messages", href: "#/messages" }]);
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
  const existing = (row.children || []).find(
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
