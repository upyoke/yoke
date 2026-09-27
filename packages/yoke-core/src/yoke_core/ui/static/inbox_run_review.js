// A run QA review in the Inbox: the visual checks one deployment run
// captured, and the person's decision on them.
//
// The card is titled for the run it asks about and links it. Its body is the
// same check list Shipping and the run page draw — each current check with
// its linked name, verdict, reason and own screenshots, earlier attempts
// folded — then the decision: a plain request with Reject and Approve while
// open, the recorded answer once decided. The run's checks are a second read,
// so the card paints its decision first and fills the checks in when they land.

import { effectiveRunChecks } from "./universe_run_evidence.js";
import { appendActions } from "./review_request_card.js";
import { decidedLabel, reviewerLine } from "./review_request_presentation.js";
import { deploymentRunHref } from "./universe_navigation.js";
import { appendRunChecks, decidedOutcome } from "./universe_run_qa_checks.js";
import { relativeTime } from "./universe_time.js";
import { callFunction, el } from "./universe_view_support.js";

const DECIDED_TONES = { approve: "is-approved", reject: "is-rejected" };

// Each card's check host, filled once the run's checks are read.
const CHECK_HOSTS = new WeakMap();

function reviewSubject(row) {
  return row.subject_context?.subject || {};
}

// A QA review of a deployment run's own checks, as opposed to a carried
// item's review or a plan-level one.
export function isRunQaReview(row) {
  if (row?.kind !== "qa_needs_review") return false;
  const subject = reviewSubject(row);
  return subject.kind === "deployment_run" && Boolean(subject.deployment_run_id)
    && subject.deployment_member_item_id == null;
}

export function reviewRunId(row) {
  return String(reviewSubject(row).deployment_run_id || "");
}

// Only a resolved request has an outcome. A reader's own vote on a request
// still open for other reviewers leaves it awaiting approval.
export function reviewDecision(row) {
  if (row.status !== "resolved") return "pending";
  return decidedOutcome(row.resolution_action || row.your_decision?.action);
}

function appendHead(documentNode, card, row, options) {
  const head = el(documentNode, "header", "review-head");
  const copy = el(documentNode, "div", "review-head-copy");
  if (options.projectLabel) {
    copy.appendChild(el(documentNode, "div", "review-kind review-project", options.projectLabel));
  }
  const title = el(documentNode, "div", "review-title");
  const runId = reviewRunId(row);
  const link = el(documentNode, "a", "run-review-link", `Run QA · ${runId}`);
  link.href = deploymentRunHref(row.project_id, runId);
  title.appendChild(link);
  copy.appendChild(title);
  const requested = row.created_at || row.requested_at;
  if (requested) {
    const context = el(documentNode, "div", "review-context");
    context.appendChild(el(documentNode, "span", null, "requested "));
    context.appendChild(relativeTime(documentNode, requested));
    copy.appendChild(context);
  }
  head.appendChild(copy);
  const decided = decidedLabel(row);
  if (decided) {
    head.appendChild(el(documentNode, "span",
      `review-state ${DECIDED_TONES[row.your_decision?.action] || ""}`, decided));
  }
  card.appendChild(head);
}

function appendDecision(documentNode, main, card, row, options) {
  const canAct = row.status !== "resolved" && !row.decided_by_you
    && row.can_act !== false && typeof options.onAct === "function"
    && !options.compact && Array.isArray(row.actions) && row.actions.length;
  if (canAct) {
    const ask = el(documentNode, "div", "run-decision-ask");
    ask.appendChild(el(documentNode, "p", null, "Approve or reject the visual result."));
    appendActions(documentNode, ask, card, row, options.onAct);
    main.appendChild(ask);
    return;
  }
  const who = reviewerLine(row);
  if (who) main.appendChild(el(documentNode, "p", "review-who", who));
}

// `options`: onAct(row, action, card, note), compact, projectLabel.
export function runQaReviewCard(context, row, options = {}) {
  const documentNode = context.document;
  const card = el(documentNode, "article", `review-card run-qa-review${
    options.compact ? " compact" : ""}${
    row.decided_by_you || row.status === "resolved" ? " decided" : ""}`);
  card.setAttribute("data-request-id", String(row.id ?? ""));
  const main = el(documentNode, "div", "review-main");
  card.appendChild(main);
  appendHead(documentNode, main, row, options);
  const checks = el(documentNode, "div", "run-qa-review-checks");
  CHECK_HOSTS.set(card, checks);
  main.appendChild(checks);
  appendDecision(documentNode, main, card, row, options);
  return card;
}

// Draws a run's checks into its review card: current checks under the
// person's decision state, replaced attempts folded after them.
export function fillRunQaReviewChecks(context, card, row, rows) {
  const host = CHECK_HOSTS.get(card);
  if (!host) return;
  const runRows = (rows || []).filter((check) => check.deployment_member_item_id == null);
  const current = effectiveRunChecks(runRows);
  const history = runRows.filter((check) => !current.includes(check));
  host.replaceChildren();
  appendRunChecks(context, host, current, history, reviewDecision(row));
}

// One QA activity read per run under review, shared by every card that
// names the run.
export async function loadRunQaReviewChecks(context, rows) {
  const byRun = new Map();
  for (const row of rows) {
    const runId = reviewRunId(row);
    if (!runId || byRun.has(runId)) continue;
    byRun.set(runId, callFunction(context.client, "qa.activity.list", {
      project: String(row.project_id), deployment_run_id: runId, limit: 100,
    }).then((read) => (
      read.status === 200 && read.envelope.success
        ? read.envelope.result?.rows || [] : []
    ), () => []));
  }
  const checks = new Map();
  for (const [runId, pending] of byRun) checks.set(runId, await pending);
  return checks;
}

export const inboxRunReview = {
  fillRunQaReviewChecks,
  isRunQaReview,
  loadRunQaReviewChecks,
  reviewDecision,
  reviewRunId,
  runQaReviewCard,
};
