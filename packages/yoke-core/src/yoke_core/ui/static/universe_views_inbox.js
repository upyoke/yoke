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
} from "./inbox_rows.js";
import { reviewRequestCard } from "./review_request_card.js";

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
  const messages = overviewSection(documentNode, "inbox-messages", "Messages");
  const decided = overviewSection(documentNode, "inbox-decided", "Decided");
  const host = el(documentNode, "div", "inbox-sections");
  host.appendChild(waiting);
  host.appendChild(messages);
  host.appendChild(decided);
  main.replaceChildren(host);

  // A single-project scope needs no project label on its cards; a merged
  // scope names the project each decision belongs to.
  const labelled = !(Array.isArray(scope) && scope.length === 1);
  const rowProject = (row) => (labelled ? projectLabel(context, row) || null : null);
  const payload = scope === "all"
    ? {} : { project_ids: scope.map((value) => Number(value)) };

  // The server lists only what still waits. A decision you answered here
  // stays on the page, in its decided state, until you leave it — the row
  // the next read no longer returns is remembered from the moment you
  // answered it.
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
      for (const section of [waiting, messages, decided]) {
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
    cardList(documentNode, waiting.body, pending.map((row) => reviewRequestCard(
      context, row, { onAct: resolve, projectLabel: rowProject(row) },
    )), "Nothing is waiting on you.");

    const messageRows = result.messages || [];
    messages.setCount(Number(result.pending_actor_message_count || 0));
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
