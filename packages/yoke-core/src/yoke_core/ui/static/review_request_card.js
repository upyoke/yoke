// One card for every decision a person is asked to make.
//
// A release approval, a work approval and a QA review used to be three
// shapes across three surfaces — an Inbox row, a run-card gate block, a
// verification row — each with its own words for the same facts. This is
// the one shape: what kind of ask it is, what it is about, what a yes does,
// the evidence, who settles it, and the answer. The Inbox draws it whole; a
// run card folds it in without a second frame; a decided list draws it
// small.

import { relativeTime } from "./universe_time.js";
import { el } from "./universe_view_support.js";
import {
  ACTION_LABELS,
  ACTION_RANK,
  decisionLinks,
  decisionTitle,
} from "./inbox_presentation.js";
import { appendRequestDetails } from "./decision_gate_body.js";
import { evidenceStrip } from "./review_evidence_strip.js";
import {
  contextLine,
  decidedLabel,
  effectLine,
  evidenceOf,
  kindLabel,
  qaFacts,
  reviewerLine,
} from "./review_request_presentation.js";

const NO_QA_EVIDENCE = "No evidence attached. This run recorded no artifacts, "
  + "so a pass or fail here would be a verdict on nothing.";

const DECIDED_TONES = {
  approve: "is-approved",
  waive: "is-waived",
  reject: "is-rejected",
  deny: "is-rejected",
  request_changes: "is-rejected",
};

function appendHead(documentNode, card, row, options) {
  const head = el(documentNode, "header", "review-head");
  const copy = el(documentNode, "div", "review-head-copy");
  const kind = el(documentNode, "div", "review-kind", kindLabel(row));
  if (options.projectLabel) {
    kind.appendChild(el(documentNode, "span", null, " · "));
    kind.appendChild(el(documentNode, "span", "review-project", options.projectLabel));
  }
  copy.appendChild(kind);
  copy.appendChild(el(documentNode, "div", "review-title", decisionTitle(row)));
  const context = el(documentNode, "div", "review-context");
  const facts = contextLine(row);
  if (facts) context.appendChild(el(documentNode, "span", null, facts));
  const requested = row.created_at || row.requested_at;
  if (requested) {
    context.appendChild(el(documentNode, "span", null, `${facts ? " · " : ""}requested `));
    context.appendChild(relativeTime(documentNode, requested));
  }
  copy.appendChild(context);
  head.appendChild(copy);
  const decided = decidedLabel(row);
  if (decided) {
    head.appendChild(el(
      documentNode,
      "span",
      `review-state ${DECIDED_TONES[row.your_decision?.action] || ""}`,
      decided,
    ));
  }
  card.appendChild(head);
}

function appendQaBody(documentNode, card, row) {
  const facts = qaFacts(row);
  if (!facts.length) return;
  const list = el(documentNode, "dl", "review-qa");
  for (const [term, value] of facts) {
    list.appendChild(el(documentNode, "dt", null, term));
    list.appendChild(el(documentNode, "dd", null, value));
  }
  card.appendChild(list);
  if (!row.decided_by_you) {
    card.appendChild(el(documentNode, "p", "review-question", "Is this acceptable?"));
  }
}

function appendEvidence(context, card, row, compact) {
  const documentNode = context.document;
  const evidence = evidenceOf(row);
  const strip = evidenceStrip(context, evidence.artifacts, {
    compact,
    requirementId: evidence.requirementId,
    // A QA review with nothing behind it must say so: a verdict on nothing
    // is the case the warning exists for. A release or work approval whose
    // subject simply has no screenshots is not a defect, so it says nothing.
    emptyNote: row.kind === "qa_needs_review" ? NO_QA_EVIDENCE : null,
  });
  if (strip) card.appendChild(strip);
  if (evidence.note) {
    card.appendChild(el(documentNode, "div", "review-evidence-note", evidence.note));
  }
}

function appendLinks(documentNode, host, row) {
  const links = decisionLinks(row);
  if (!links.length) return;
  const wrap = el(documentNode, "div", "review-links");
  for (const link of links) {
    const anchor = el(documentNode, "a", "review-link", link.label);
    anchor.href = link.href;
    wrap.appendChild(anchor);
  }
  host.appendChild(wrap);
}

function composer(documentNode, card, row, action, onAct) {
  if (Array.from(card.children).some(
    (child) => child.classList.contains("review-note-composer"),
  )) {
    return;
  }
  const wrap = el(documentNode, "div", "review-note-composer");
  const note = el(documentNode, "textarea", "item-form-control review-note");
  note.setAttribute("aria-label", "Change request note");
  note.setAttribute("placeholder", "What needs to change?");
  wrap.appendChild(note);
  const cancel = el(documentNode, "button", "item-button review-action", "Cancel");
  cancel.type = "button";
  cancel.addEventListener("click", () => card.removeChild(wrap));
  wrap.appendChild(cancel);
  const send = el(
    documentNode, "button", "item-button review-action primary", "Request changes",
  );
  send.type = "button";
  send.addEventListener("click", () => {
    if (!String(note.value || "").trim()) {
      note.classList.add("invalid");
      return;
    }
    onAct(row, action, card, String(note.value).trim());
  });
  wrap.appendChild(send);
  card.appendChild(wrap);
}

function appendActions(documentNode, foot, card, row, onAct) {
  const actions = el(documentNode, "div", "review-actions");
  const ordered = [...(Array.isArray(row.actions) ? row.actions : [])].sort(
    (left, right) => Number(ACTION_RANK[left] ?? 1) - Number(ACTION_RANK[right] ?? 1),
  );
  for (const action of ordered) {
    const button = el(
      documentNode,
      "button",
      `item-button review-action${action === "approve" ? " primary" : ""}`,
      ACTION_LABELS[action] || action,
    );
    button.type = "button";
    button.setAttribute("data-action", action);
    button.addEventListener("click", (event) => {
      // A card inside a linked run card must answer without navigating.
      if (typeof event.preventDefault === "function") event.preventDefault();
      if (typeof event.stopPropagation === "function") event.stopPropagation();
      if (action === "request_changes") composer(documentNode, card, row, action, onAct);
      else onAct(row, action, card);
    });
    actions.appendChild(button);
  }
  foot.appendChild(actions);
}

// `options.inline` folds the card into a host that already names the
// subject (a run card), so the head is the host's. `options.compact` is the
// small decided form. `options.onAct(row, action, card, note)` answers.
export function reviewRequestCard(context, row, options = {}) {
  const documentNode = context.document;
  const compact = Boolean(options.compact);
  const card = el(
    documentNode,
    "article",
    `review-card${compact ? " compact" : ""}${options.inline ? " inline" : ""}${
      row.decided_by_you ? " decided" : ""
    }`,
  );
  card.setAttribute("data-request-id", String(row.id ?? row.request_id ?? ""));
  if (!options.inline) appendHead(documentNode, card, row, options);
  const effect = effectLine(row);
  if (effect) card.appendChild(el(documentNode, "p", "review-effect", effect));
  if (row.kind === "qa_needs_review") appendQaBody(documentNode, card, row);
  appendEvidence(context, card, row, compact);
  if (!compact) appendRequestDetails(context, card, row);
  const foot = el(documentNode, "footer", "review-foot");
  const who = reviewerLine(row);
  if (who) foot.appendChild(el(documentNode, "span", "review-who", who));
  appendLinks(documentNode, foot, row);
  const canAct = !row.decided_by_you && row.can_act !== false
    && typeof options.onAct === "function" && !compact;
  if (canAct) appendActions(documentNode, foot, card, row, options.onAct);
  if (foot.children.length) card.appendChild(foot);
  return card;
}

export const reviewRequestCardView = { reviewRequestCard };
