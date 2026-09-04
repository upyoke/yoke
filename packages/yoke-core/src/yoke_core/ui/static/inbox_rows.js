import { callFunction, el } from "./universe_view_support.js";
import { relativeTime } from "./universe_time.js";
import {
  ACTION_LABELS,
  ACTION_RANK,
  decisionSubtitle,
  decisionTitle,
  KIND_PRESENTATION,
  subjectHref,
  yourDecisionText,
} from "./inbox_presentation.js";
import { senderDescription } from "./universe_session_message_actors.js";

function eventCameFromControl(event, row) {
  let target = event.target;
  while (target && target !== row) {
    if (["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "TIME"].includes(
      String(target.tagName || "").toUpperCase(),
    )) return true;
    target = target.parentNode;
  }
  return false;
}

function makeRowNavigable(documentNode, row, href, label) {
  row.tabIndex = 0;
  row.setAttribute("role", "link");
  row.setAttribute("aria-label", `Open ${label}`);
  row.addEventListener("click", (event) => {
    if (eventCameFromControl(event, row)) return;
    documentNode.defaultView.location.hash = href;
  });
  row.addEventListener("keydown", (event) => {
    if (eventCameFromControl(event, row)) return;
    if (!["Enter", " "].includes(event.key)) return;
    if (typeof event.preventDefault === "function") event.preventDefault();
    documentNode.defaultView.location.hash = href;
  });
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
  const title = el(documentNode, "a", "inbox-row-title", decisionTitle(row));
  const href = subjectHref(row);
  title.href = href;
  main.appendChild(title);
  const subtitle = decisionSubtitle(row);
  main.appendChild(timedSubtitle(
    documentNode,
    subtitle.leading,
    row.created_at,
    subtitle.timeVerb,
    subtitle.trailing,
    projectLabel,
  ));
  wrap.appendChild(main);
  const actions = el(documentNode, "div", "inbox-actions");
  if (row.decided_by_you) {
    // A decision is final for the person who made it; under an all-approvers
    // policy the gate stays open for everyone else, so this row reports their
    // own answer rather than offering an action they cannot take again.
    actions.appendChild(el(
      documentNode, "span", "inbox-decided", yourDecisionText(row),
    ));
    wrap.appendChild(actions);
    makeRowNavigable(documentNode, wrap, href, decisionTitle(row));
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
  makeRowNavigable(documentNode, wrap, href, decisionTitle(row));
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
    const collect = (node) => {
      if (node.classList?.contains("inbox-action")) actionButtons.push(node);
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
  const href = "#/messages";
  const title = el(
    documentNode,
    "a",
    "inbox-row-title",
    String(message.body || "Message body unavailable"),
  );
  title.href = href;
  main.appendChild(title);
  main.appendChild(timedSubtitle(
    documentNode,
    `From ${senderDescription(message)}`,
    message.created_at,
  ));
  wrap.appendChild(main);
  if (message.actor_receipt?.state === "pending") {
    const button = el(documentNode, "button", "inbox-read", "Acknowledge");
    button.type = "button";
    button.addEventListener("click", () => acknowledge(message.message_id, button));
    wrap.appendChild(button);
  }
  makeRowNavigable(documentNode, wrap, href, "message");
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
