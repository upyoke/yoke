// Per-actor needs-you surface: governed decisions, requests, and notifications.

import { buildUniverseRoute } from "./universe_navigation.js";
import {
  callFunction,
  el,
  loadScopedPanels,
  section,
} from "./universe_view_support.js";

const KIND_PRESENTATION = {
  deployment_stage_approval: { icon: "⬈", fallback: "Approve deployment stage" },
  qa_needs_review: { icon: "◉", fallback: "QA evidence needs your review" },
  lifecycle_transition_approval: { icon: "≣", fallback: "Approve lifecycle transition" },
  machine_approval: { icon: "⚇", fallback: "Approve a new machine" },
  strategy_revision_review: { icon: "❖", fallback: "Review a strategy revision" },
};

const ACTION_LABELS = {
  approve: "Approve",
  reject: "Reject",
  waive: "Waive",
  deny: "Deny",
  request_changes: "Request changes",
};

function subjectHref(row) {
  const facts = row.subject_context || {};
  if (facts.href) return String(facts.href);
  if (row.kind === "deployment_stage_approval") {
    return buildUniverseRoute("delivery", row.project_id, "runs");
  }
  if (row.kind === "qa_needs_review") {
    return buildUniverseRoute("qa", row.project_id);
  }
  if (row.kind === "lifecycle_transition_approval") {
    const item = String(facts.item_id || facts.item_ref || "")
      .replace(/^[A-Z]+-/, "");
    return buildUniverseRoute("items", row.project_id, item || null);
  }
  if (row.kind === "machine_approval") return buildUniverseRoute("access", null);
  if (row.kind === "strategy_revision_review") {
    return buildUniverseRoute("strategy", row.project_id, facts.slug || null);
  }
  return buildUniverseRoute("inbox", row.project_id);
}

function decisionSubtitle(row) {
  const facts = row.subject_context || {};
  const details = [];
  if (facts.summary) details.push(facts.summary);
  else if (row.kind === "deployment_stage_approval") {
    if (facts.run_id) details.push(facts.run_id);
    if (facts.stage) details.push(`${facts.stage} stage`);
  } else if (row.kind === "qa_needs_review") {
    for (const value of [
      facts.plan_name, facts.case_name, facts.method_name, facts.evidence_summary,
    ]) if (value) details.push(value);
  } else if (row.kind === "lifecycle_transition_approval") {
    if (facts.policy_summary) details.push(facts.policy_summary);
    else if (facts.transition) details.push(`${facts.transition} transition`);
  } else if (row.kind === "machine_approval" && facts.code) {
    details.push(`one-time code ${facts.code}`);
  } else if (row.kind === "strategy_revision_review") {
    if (facts.author_label) details.push(`revision by ${facts.author_label}`);
    if (facts.revision) details.push(`revision ${facts.revision}`);
    details.push("the document stays live while this waits");
  }
  if (row.created_at) details.push(`requested ${row.created_at}`);
  if (row.authority_reason) details.push(`you: ${row.authority_reason}`);
  return details.join(" · ");
}

function decisionTitle(row) {
  const facts = row.subject_context || {};
  if (facts.title) return String(facts.title);
  const presentation = KIND_PRESENTATION[row.kind] || {};
  if (facts.item_ref && row.kind === "lifecycle_transition_approval") {
    return `${facts.item_ref} — approve the ${facts.transition || "next"} transition`;
  }
  if (facts.case_name && row.kind === "qa_needs_review") {
    return `${facts.case_name} needs your review`;
  }
  if (facts.slug && row.kind === "strategy_revision_review") {
    return `${facts.slug} — review a revision`;
  }
  return presentation.fallback || row.subject_key;
}

function notificationPresentation(row) {
  const facts = (row.event && row.event.context) || {};
  if (facts.title) {
    return { title: facts.title, subtitle: facts.summary || row.reason };
  }
  if (row.notification_kind === "deployment_run_completed") {
    const target = facts.target_env || "Deployment";
    return {
      title: `${target} deploy completed`,
      subtitle: [facts.run_id, row.event_outcome, row.created_at]
        .filter(Boolean).join(" · "),
    };
  }
  if (row.notification_kind === "item_block_state_changed") {
    const state = row.event_name === "ItemUnblocked" ? "unblocked" : "blocked";
    return {
      title: `${facts.item_ref || "Item"} ${state}`,
      subtitle: [facts.reason, row.created_at].filter(Boolean).join(" · "),
    };
  }
  return {
    title: "Your decision request was resolved",
    subtitle: [row.reason, facts.resolution_actor_label, row.created_at]
      .filter(Boolean).join(" · "),
  };
}

function appendPanelHint(documentNode, panel, text) {
  panel.children[0].appendChild(el(documentNode, "span", "inbox-panel-hint", text));
}

function appendDecisionRow(
  context, body, row, invoke, busyRequestId,
) {
  const documentNode = context.document;
  const wrap = el(documentNode, "article", "inbox-row");
  wrap.setAttribute("data-request-id", row.id);
  const presentation = KIND_PRESENTATION[row.kind] || { icon: "•" };
  wrap.appendChild(el(documentNode, "span", "inbox-icon", presentation.icon));
  const main = el(documentNode, "div", "inbox-row-main");
  const title = el(documentNode, "a", "inbox-row-title", decisionTitle(row));
  title.href = subjectHref(row);
  main.appendChild(title);
  main.appendChild(el(
    documentNode, "div", "inbox-row-subtitle", decisionSubtitle(row),
  ));
  if (row.asked_of_you) {
    main.appendChild(el(documentNode, "span", "inbox-addressed", "asked of you"));
  }
  wrap.appendChild(main);
  const actions = el(documentNode, "div", "inbox-actions");
  for (const action of row.actions || []) {
    const button = el(
      documentNode, "button",
      `btn inbox-action${action === "approve" ? " primary" : ""}`,
      ACTION_LABELS[action] || action,
    );
    button.type = "button";
    button.disabled = busyRequestId === row.id;
    button.setAttribute("data-action", action);
    button.addEventListener("click", () => {
      if (action !== "request_changes") {
        invoke(row, action, button);
        return;
      }
      if (Array.from(wrap.children).some(
        (child) => child.classList.contains("inbox-note-composer"),
      )) return;
      const composer = el(documentNode, "div", "inbox-note-composer");
      const note = el(documentNode, "textarea", "inbox-note");
      note.setAttribute("aria-label", "Change request note");
      note.setAttribute("placeholder", "What needs to change?");
      composer.appendChild(note);
      const cancel = el(documentNode, "button", "btn", "Cancel");
      cancel.type = "button";
      cancel.addEventListener("click", () => wrap.removeChild(composer));
      composer.appendChild(cancel);
      const send = el(documentNode, "button", "btn primary", "Request changes");
      send.type = "button";
      send.addEventListener("click", () => {
        if (!String(note.value || "").trim()) {
          note.classList.add("invalid");
          return;
        }
        invoke(row, action, send, String(note.value).trim());
      });
      composer.appendChild(send);
      wrap.appendChild(composer);
    });
    actions.appendChild(button);
  }
  wrap.appendChild(actions);
  body.appendChild(wrap);
}

function appendNotificationRow(context, body, row, markRead) {
  const documentNode = context.document;
  const wrap = el(documentNode, "article", "inbox-row");
  const icon = row.notification_kind === "deployment_run_completed"
    ? "⬈" : row.notification_kind === "item_block_state_changed" ? "≋" : "✓";
  wrap.appendChild(el(documentNode, "span", "inbox-icon", icon));
  const main = el(documentNode, "div", "inbox-row-main");
  const presentation = notificationPresentation(row);
  main.appendChild(el(documentNode, "div", "inbox-row-title", presentation.title));
  main.appendChild(el(
    documentNode, "div", "inbox-row-subtitle", presentation.subtitle,
  ));
  wrap.appendChild(main);
  const button = el(documentNode, "button", "inbox-read", "Mark read");
  button.type = "button";
  button.addEventListener("click", () => markRead(row.id, button));
  wrap.appendChild(button);
  body.appendChild(wrap);
}

function emptyRow(documentNode, body, message) {
  body.appendChild(el(documentNode, "p", "empty inbox-empty", message));
}

export function renderInboxView(context, main, scope) {
  const documentNode = context.document;
  const needs = section(
    documentNode, "Needs your decision", { showRaw: false },
  );
  const requests = section(documentNode, "Requests", { showRaw: false });
  const notifications = section(
    documentNode, "Notifications", { showRaw: false },
  );
  appendPanelHint(documentNode, needs, "the gate waits until you resolve");
  appendPanelHint(documentNode, requests, "waiting, but nothing is halted");
  const markAll = el(documentNode, "button", "inbox-read inbox-read-all", "Mark all read");
  markAll.type = "button";
  notifications.children[0].appendChild(markAll);
  main.replaceChildren(needs, requests, notifications);

  let busyRequestId = null;
  const payload = scope === "all"
    ? {} : { project_ids: scope.map((value) => Number(value)) };
  const load = () => loadScopedPanels(context, [
    [needs, (body, calls) => {
      const rows = calls[0].envelope.result.needs_decision || [];
      needs.setCount(rows.length);
      if (!rows.length) emptyRow(documentNode, body, "Nothing is waiting on you.");
      for (const row of rows) {
        appendDecisionRow(context, body, row, resolve, busyRequestId);
      }
    }],
    [requests, (body, calls) => {
      const rows = calls[0].envelope.result.requests || [];
      requests.setCount(rows.length);
      if (!rows.length) emptyRow(documentNode, body, "No open requests.");
      for (const row of rows) {
        appendDecisionRow(context, body, row, resolve, busyRequestId);
      }
    }],
    [notifications, (body, calls) => {
      const rows = calls[0].envelope.result.notifications || [];
      notifications.setCount(rows.length);
      markAll.disabled = rows.length === 0;
      if (!rows.length) emptyRow(documentNode, body, "Nothing new.");
      for (const row of rows) appendNotificationRow(context, body, row, readOne);
    }],
  ], [{ functionId: "inbox.list", payload }]);

  const resolve = async (row, action, button, note = null) => {
    busyRequestId = row.id;
    button.disabled = true;
    const resolution = { request_id: row.id, action };
    if (note) resolution.note = note;
    const result = await callFunction(
      context.client, "decision_requests.resolve", resolution,
    );
    busyRequestId = null;
    if (result.status === 200 && result.envelope.success) await load();
    else button.disabled = false;
  };
  const readOne = async (notificationId, button) => {
    button.disabled = true;
    const result = await callFunction(context.client, "notifications.read", {
      notification_id: notificationId,
    });
    if (result.status === 200 && result.envelope.success) await load();
    else button.disabled = false;
  };
  markAll.addEventListener("click", async () => {
    markAll.disabled = true;
    const result = await callFunction(
      context.client, "notifications.read_all", {},
    );
    if (result.status === 200 && result.envelope.success) await load();
    else markAll.disabled = false;
  });
  load();
}


export const inboxPresentation = {
  decisionSubtitle,
  decisionTitle,
  notificationPresentation,
  subjectHref,
};
