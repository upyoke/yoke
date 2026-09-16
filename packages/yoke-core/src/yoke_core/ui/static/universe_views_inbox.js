// Per-actor needs-you surface: the decisions waiting on you, the messages
// sent to you, and what you have already decided.

import {
  callFunction,
  el,
  renderError,
  settledScopedCalls,
} from "./universe_view_support.js";
import { overviewSection } from "./universe_overview_primitives.js";
import {
  appendActorMessageRow,
  appendRowError,
  createDecisionResolver,
  emptyRow,
  NOTICE_LABELS,
} from "./inbox_rows.js";
import { reviewRequestCard } from "./review_request_card.js";
import {
  appendCarriedItemEvidence,
  loadCarriedItemEvidence,
} from "./universe_carried_item_evidence.js";

export { inboxPresentation } from "./inbox_presentation.js";

function projectLabel(context, row) {
  const projects = typeof context.projects === "function"
    ? context.projects() : [];
  const rowLabel = row.project_slug || row.project;
  const rowKey = row.project_id ?? rowLabel;
  const project = projects.find((candidate) => (
    [candidate.id, candidate.slug, candidate.name].some(
      (value) => String(value) === String(rowKey),
    )
  ));
  const label = rowLabel || project?.slug || project?.name || row.project_id;
  return label == null ? "" : String(label);
}

// What this approval ships, and on whose authority the list is known.
//
// Two different records answer that. Derived lineage — the trunk changes
// between this release and the last — is the fuller answer, and it is the
// one shown whenever the deriver could compute it. When it could not (no
// commit lineage to compare, no checkout to read), its item list is empty,
// and an empty derivation is not an empty release: the run's own explicit
// membership is still a known fact, and reading the unknown as "carries
// nothing" hid the very item a reviewer was asked to look at. So membership
// is the fallback, and the block says which of the two it is showing.
//
// Membership rows name the item as `item_ref`; derived rows name it `ref`.
// Both are normalized here so one renderer draws either shape.
const CARRIED_BASIS_DERIVED = "derived";
const CARRIED_BASIS_MEMBERSHIP = "membership";

function approvalCarried(row) {
  if (row.kind !== "deployment_stage_approval") {
    return { items: [], basis: null };
  }
  const context = row.subject_context || {};
  const derived = context.carried?.items || [];
  const basis = derived.length ? CARRIED_BASIS_DERIVED : CARRIED_BASIS_MEMBERSHIP;
  const source = derived.length ? derived : (context.batch?.items || []);
  return {
    basis,
    items: source.map((item) => ({
      ...item,
      ref: item.ref || item.item_ref,
      project_id: item.project_id ?? row.project_id,
      run_id: context.run_id,
    })),
  };
}

// A release approval decides a deployment, not the QA its carried items
// recorded. Showing that QA here is supporting context for the person
// approving, so the block says which decision it is not: each item review
// under it is its own request, answered on its own terms.
function appendApprovalCarried(context, card, row, facts, onDecide) {
  const { items, basis } = approvalCarried(row);
  if (!items.length) return;
  const documentNode = context.document;
  const wrap = el(documentNode, "div", "approval-carried");
  wrap.appendChild(el(
    documentNode,
    "span",
    "overview-run-batch-title",
    `Carries · ${items.length} item${items.length === 1 ? "" : "s"}`,
  ));
  wrap.appendChild(el(
    documentNode,
    "p",
    "approval-carried-note",
    (basis === CARRIED_BASIS_MEMBERSHIP
      ? "This run's declared members; its release lineage could not be "
        + "derived, so trunk changes beyond these are unknown. "
      : "")
      + "Supporting context. Approving this deployment does not approve these "
      + "items' QA — each review below is its own request.",
  ));
  for (const item of items) {
    const entry = el(documentNode, "div", "overview-run-member");
    entry.appendChild(el(
      documentNode, "code", null, item.ref || `item ${item.item_id}`,
    ));
    entry.appendChild(el(documentNode, "span", null, item.title || ""));
    appendCarriedItemEvidence(context, entry, {
      item,
      runId: row.subject_context?.run_id,
      facts,
      onDecide,
    });
    wrap.appendChild(entry);
  }
  card.appendChild(wrap);
}

function cardList(documentNode, body, cards, emptyText) {
  body.replaceChildren();
  if (!cards.length) {
    if (emptyText) emptyRow(documentNode, body, emptyText);
    return;
  }
  const list = el(documentNode, "div", "review-list");
  for (const card of cards) list.appendChild(card);
  body.appendChild(list);
}

export function renderInboxView(context, main, scope) {
  const documentNode = context.document;
  const waiting = overviewSection(documentNode, "inbox-waiting", "Waiting on you");
  // A delivery notice asks for nothing, so it does not belong beside the
  // decisions that do, and it does not belong among messages a person sent
  // either — reading one as the other is how a report gets answered and a
  // question gets dismissed.
  const notices = overviewSection(documentNode, "inbox-notices", "Notices");
  const messages = overviewSection(documentNode, "inbox-messages", "Messages");
  const decided = overviewSection(documentNode, "inbox-decided", "Decided");
  const host = el(documentNode, "div", "inbox-sections");
  host.appendChild(waiting);
  host.appendChild(notices);
  host.appendChild(messages);
  host.appendChild(decided);
  main.replaceChildren(host);

  // A single-project scope needs no project label on its cards; a merged
  // scope names the project each decision belongs to.
  const labelled = !(Array.isArray(scope) && scope.length === 1);
  const rowProject = (row) => (labelled ? projectLabel(context, row) || null : null);
  const payload = scope === "all"
    ? {} : { project_ids: scope.map((value) => Number(value)) };

  // The server lists what still waits plus a tail of what this reader
  // already settled, so the decided list survives a reload. Between
  // answering a request and the next read returning it, the row is
  // remembered here so it never blinks out of the page in between.
  const answered = new Map();
  const remember = (row, action) => {
    answered.set(String(row.id), {
      ...row,
      decided_by_you: true,
      your_decision: { action },
      actions: [],
    });
  };

  const load = async () => {
    const { callResults, failed } = await settledScopedCalls(
      context, [{ functionId: "inbox.list", payload }],
    );
    if (!context.isMounted()) return;
    if (failed) {
      for (const section of [waiting, notices, messages, decided]) {
        section.body.replaceChildren();
        renderError(section.body, failed);
      }
      return;
    }
    const result = callResults[0].envelope.result || {};
    const rows = result.needs_decision || [];
    const pending = rows.filter((row) => !row.decided_by_you);
    const served = rows.filter((row) => row.decided_by_you);
    for (const row of served) answered.delete(String(row.id));
    const done = [...served, ...answered.values()];

    waiting.setCount(pending.length);
    const cards = new Map();
    cardList(documentNode, waiting.body, pending.map((row) => {
      const card = reviewRequestCard(
        context, row, { onAct: resolve, projectLabel: rowProject(row) },
      );
      cards.set(row, card);
      return card;
    }), "Nothing is waiting on you.");
    // What each carried item proved is a second read, so the Inbox paints
    // its decisions first and fills that context in when it lands.
    appendCarriedContext(pending, cards);

    const allMessages = result.messages || [];
    const noticeRows = allMessages.filter((row) => NOTICE_LABELS[row.notice_kind]);
    const messageRows = allMessages.filter((row) => !NOTICE_LABELS[row.notice_kind]);
    const pendingIn = (rows) => rows.filter(
      (row) => row.actor_receipt?.state === "pending",
    ).length;

    // No notices means no section, the same way nothing decided means none.
    notices.setCount(pendingIn(noticeRows));
    notices.hidden = !noticeRows.length;
    notices.body.replaceChildren();
    for (const row of noticeRows) {
      appendActorMessageRow(context, notices.body, row, acknowledgeMessage);
    }

    messages.setCount(pendingIn(messageRows));
    messages.body.replaceChildren();
    if (!messageRows.length) emptyRow(documentNode, messages.body, "No unread messages.");
    for (const row of messageRows) {
      appendActorMessageRow(context, messages.body, row, acknowledgeMessage);
    }

    // Nothing decided means no section, not an empty one.
    decided.setCount(done.length);
    decided.hidden = !done.length;
    cardList(documentNode, decided.body, done.map((row) => reviewRequestCard(
      context, row, { compact: true, projectLabel: rowProject(row) },
    )), "");
  };

  // One batched read for every release approval on the page, then the
  // shared carried-item renderer — the same loader and the same entry the
  // deployment cards use, so the association labels cannot drift apart.
  const appendCarriedContext = async (pending, cards) => {
    const subjects = pending.flatMap((row) => approvalCarried(row).items);
    if (!subjects.length) return;
    const facts = await loadCarriedItemEvidence(context, subjects);
    if (!context.isMounted()) return;
    for (const [row, card] of cards) {
      appendApprovalCarried(context, card, row, facts, resolve);
    }
  };

  const resolveOnServer = createDecisionResolver(context, load);
  const resolve = (row, action, card, note) => {
    remember(row, action);
    return resolveOnServer(row, action, card, note).then(() => {
      // A refused resolution leaves the row where it was; forgetting it here
      // keeps the page from claiming a decision the server never recorded.
      if (Array.from(card.children).some(
        (child) => child.classList.contains("inbox-row-error"),
      )) {
        answered.delete(String(row.id));
      }
    });
  };

  const acknowledgeMessage = async (messageId, button) => {
    button.disabled = true;
    let result;
    try {
      result = await callFunction(
        context.client,
        "session_control.message.acknowledge",
        { message_id: messageId },
      );
    } catch (error) {
      result = {
        status: 0,
        envelope: { success: false, error: { message: String(error) } },
      };
    }
    if (result.status === 200 && result.envelope.success) {
      await load();
      return;
    }
    button.disabled = false;
    appendRowError(
      documentNode,
      button.parentNode,
      result.envelope.error?.message || "The message could not be acknowledged.",
    );
  };

  load();
}
