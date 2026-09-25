// Waiting, Ready, Active, Release and Done are five readings of one item
// roster, so they are computed together: an item appears in exactly one of
// them, and each band's count is the number of cards it drew.
//
// Which band a card sits in and who is holding it are separate facts. Every
// card whose item a qualifying session holds carries that session's chip,
// whichever band it landed in — a merged item parked at its release wait is
// still that session's, and the card says so.
//
// Release is the one band a status decides outright. An item that has merged
// and is waiting on its deployment is neither stopped, free to pick up, nor
// being worked on, so it is held out of the other live bands rather than
// appearing twice under two partly-true readings.
//
// Active is the band that has to be earned. Lifecycle status alone does not
// put an item here — an item whose status says implementing while nothing
// holds it is not being worked on, it is stopped — so membership is a live
// work claim held by a session the roster still calls live and whose process
// this machine has not seen die. Work held by an owner that is gone moves to
// Waiting and says so, which is the honest reading of the same facts.

import { buildUniverseRoute } from "./universe_navigation.js";
import {
  BAND_CARD_LIMIT,
  callError,
  rowsInBandScope,
  successfulResult,
} from "./universe_band_primitives.js";
import {
  appendItemClaimants,
  claimantsByItemRef,
  claimedItemRefs,
  isQualifyingClaimant,
} from "./universe_item_claimant.js";
import { appendItemDelivery } from "./universe_item_deployment.js";
import { workItemCard } from "./universe_work_cards.js";
import { el, settledScopedCalls } from "./universe_view_support.js";

const RELEASE_STATE = "release";
const LIVE_SESSION_STATES = new Set(["active", "stale"]);

function reference(row) {
  return String(row.public_ref || row.item_id || row.id || "");
}

function status(row) {
  return String(row.status || "").toLowerCase();
}

function enabled(value) {
  return value === true || value === 1 || value === "1" || value === "true";
}

function waitingReason(row, blockedRow) {
  if (enabled(row.frozen)) {
    return {
      rank: 0,
      flag: {
        label: "Frozen",
        text: row.blocked_reason || "Parked with no work scheduled.",
        tone: "frozen",
      },
    };
  }
  if (enabled(row.blocked)) {
    return {
      rank: 1,
      flag: {
        label: "Blocked",
        text: row.blocked_reason || blockedRow?.why || "Blocked without a reason.",
        tone: "blocked",
      },
    };
  }
  if (blockedRow) {
    const target = blockedRow.blocking_item
      ? ` Waits on ${blockedRow.blocking_item}.` : "";
    return {
      rank: 2,
      flag: {
        label: "Dependency",
        text: `${blockedRow.why || "An upstream fact is unsatisfied."}${target}`,
        tone: "dependency",
      },
    };
  }
  return null;
}

// Work whose only claimant is a session that is no longer answering. The
// claim is real and still held, so the item is not free to pick up; what has
// stopped is the session, and the card says that rather than showing the item
// as actively in flight.
const UNAVAILABLE_OWNER = {
  rank: 3,
  flag: {
    label: "Owner unavailable",
    text: "Held by a work claim whose session is no longer answering. "
      + "Release the claim or terminate the session to free this item.",
    tone: "dependency",
  },
};

// When the item finished, as opposed to when its code landed. The feed dates
// this from the lifecycle transition that put the item into the status it
// holds, and leaves it absent for anything that has not finished — so there is
// nothing to fall back to and nothing here to re-decide.
function finishedAt(row) {
  return row.finished_at || "";
}

// The feed resolves both facts against the item's own pinned workflow
// definition. The band asking again from a status list of its own is how it
// came to count a paused item as done and to date a finish by its merge.
function recentlyDone(row) {
  return Boolean(row.finished) && Boolean(finishedAt(row));
}

function mergeItemFacts(row, itemsByRef) {
  return { ...(itemsByRef.get(reference(row)) || {}), ...row };
}

// The overflow card is navigation, not a statistic: the band above it already
// carries its own count, so this one says only where the rest of them are.
function seeMoreCard(documentNode, scope) {
  const card = el(documentNode, "a", "work-item-card see-more-card");
  card.href = buildUniverseRoute(
    "items", scope === "all" ? null : scope.join(","),
  );
  card.setAttribute("aria-label", "See more...");
  card.appendChild(el(documentNode, "span", null, "See more..."));
  return card;
}

function liveSessions(rows, scope, projects) {
  return rowsInBandScope(rows, scope, projects).filter((row) => (
    LIVE_SESSION_STATES.has(String(row.liveness || "").toLowerCase())
  ));
}

// The stage strip for an item, when the session holding it has published one.
// The projection carries stages for a session's primary held item, so a
// session holding several items has progress for the one it leads with and
// honest silence for the rest.
function stagesByItemRef(sessions) {
  const stages = new Map();
  for (const row of sessions) {
    const ref = String(row.current_item || "");
    if (!ref || !(row.primary_item_stages || []).length) continue;
    stages.set(ref, row.primary_item_stages);
  }
  return stages;
}

export async function loadFrontier(context, bands, getScope, sessionRoster, options = {}) {
  // Every read this paint needs, in flight together. The bands are one
  // reading of one roster, so they all paint at once either way; starting
  // them in sequence only made the wait their sum.
  const [{ callResults }, sessionCalls, deployments] = await Promise.all([
    settledScopedCalls(context, [
      { functionId: "items.overview.list", payload: { relevance: "overview" } },
      { functionId: "frontier.list", payload: {} },
    ]),
    sessionRoster,
    Promise.resolve(options.deployments).catch(() => undefined),
  ]);
  if (!context.isMounted()) return null;
  const paint = () => {
    const itemsResult = successfulResult(callResults[0]);
    const frontierResult = successfulResult(callResults[1]);
    const sessionsResult = successfulResult(sessionCalls.callResults[0]);
    if (!itemsResult || !frontierResult) {
      const failed = !itemsResult ? callResults[0] : callResults[1];
      const message = callError(failed, "Frontier could not be loaded.");
      for (const band of Object.values(bands)) band.renderError(message);
      return;
    }
    if (!sessionsResult) {
      const message = callError(
        sessionCalls.callResults[0],
        "The frontier needs the session roster to tell which work is in flight.",
      );
      for (const band of Object.values(bands)) band.renderError(message);
      return;
    }
    const scope = getScope();
    const projects = context.projects();
    const documentNode = context.document;
    const items = rowsInBandScope(itemsResult.rows || [], scope, projects);
    const readyRows = rowsInBandScope(
      frontierResult.ready_rows || [], scope, projects,
    );
    const blockedRows = rowsInBandScope(
      frontierResult.blocked_rows || [], scope, projects,
    );
    const itemsByRef = new Map(items.map((row) => [reference(row), row]));
    const blockedByRef = new Map(
      blockedRows.map((row) => [reference(row), row]),
    );

    const sessions = liveSessions(sessionsResult.rows || [], scope, projects);
    const qualifying = sessions.filter(isQualifyingClaimant);
    const claimants = claimantsByItemRef(qualifying);
    const heldByAnyLiveSession = new Set(sessions.flatMap(claimedItemRefs));
    const stages = stagesByItemRef(qualifying);
    const renderFullSession = options.renderFullSession || (() => (
      el(documentNode, "p", "empty", "Session detail is unavailable here.")
    ));
    const withClaimants = (card, row) => {
      appendItemClaimants(
        documentNode, card, reference(row), claimants, renderFullSession,
      );
      return card;
    };

    const releasing = items
      .filter((row) => status(row) === RELEASE_STATE)
      .sort((left, right) => String(right.updated_at || "").localeCompare(
        String(left.updated_at || ""),
      ));
    const releasingRefs = new Set(releasing.map(reference));
    const live = items.filter((row) => (
      !row.terminal && !releasingRefs.has(reference(row))
    ));
    // Active first, because being worked on is the stronger fact: a blocked
    // item somebody is actively unblocking belongs where the work is, with
    // its reason still on the card.
    const activeRows = live.filter((row) => (
      !enabled(row.frozen) && claimants.has(reference(row))
    ));
    const activeRefs = new Set(activeRows.map(reference));

    const waiting = live
      .filter((row) => !activeRefs.has(reference(row)))
      .map((row) => {
        const ref = reference(row);
        const reason = waitingReason(row, blockedByRef.get(ref))
          || (heldByAnyLiveSession.has(ref) ? UNAVAILABLE_OWNER : null);
        return { row, reason };
      })
      .filter((entry) => entry.reason)
      .sort((left, right) => (
        left.reason.rank - right.reason.rank
        || String(right.row.updated_at || "").localeCompare(
          String(left.row.updated_at || ""),
        )
      ));
    const waitingRefs = new Set(waiting.map((entry) => reference(entry.row)));
    bands.waiting.setCount(waiting.length);
    bands.waiting.renderCards(waiting.map(({ row, reason }) => withClaimants(
      workItemCard(
        documentNode,
        row,
        scope,
        { flag: reason.flag, timestamp: row.created_at, timeLabel: "filed" },
      ),
      row,
    )), "Nothing is stopped.");

    bands.active.setCount(activeRows.length);
    bands.active.renderCards(
      activeRows
        .sort((left, right) => String(right.updated_at || "").localeCompare(
          String(left.updated_at || ""),
        ))
        .map((row) => {
          const ref = reference(row);
          const blocker = waitingReason(row, blockedByRef.get(ref));
          return withClaimants(workItemCard(documentNode, row, scope, {
            flag: blocker?.flag,
            stages: stages.get(ref) || [],
            timestamp: row.updated_at,
          }), row);
        }),
      "No session is running against this universe.",
    );

    const ready = readyRows
      .map((row) => mergeItemFacts(row, itemsByRef))
      .filter((row) => !releasingRefs.has(reference(row)))
      .filter((row) => !waitingRefs.has(reference(row)))
      .filter((row) => !activeRefs.has(reference(row)))
      .filter((row) => !heldByAnyLiveSession.has(reference(row)));
    bands.ready.setCount(ready.length);
    bands.ready.renderCards(ready.map((row) => workItemCard(
      documentNode,
      row,
      scope,
      {
        flag: {
          label: "Ready",
          text: row.why_ready || "No blocker is holding this item.",
          tone: "ready",
        },
        meta: row.run_command || row.next_step,
        timestamp: row.created_at,
        timeLabel: "filed",
      },
    )), "Nothing is ready to pick up.");

    // Every card, with no overflow tile: Done is the one band that truncates,
    // because it is a window on finished work that only grows. Release is a
    // queue somebody is waiting to see empty, and a hidden remainder there
    // would understate what is still unshipped.
    bands.release.setCount(releasing.length);
    bands.release.renderCards(releasing.map((row) => {
      const card = workItemCard(documentNode, row, scope, {
        timestamp: row.updated_at,
      });
      appendItemDelivery(documentNode, card, row, deployments);
      return withClaimants(card, row);
    }), "Nothing is waiting to ship.");

    const done = items
      .filter((row) => recentlyDone(row))
      .sort((left, right) => finishedAt(right).localeCompare(finishedAt(left)));
    const visible = done.slice(0, BAND_CARD_LIMIT).map((row) => {
      // Terminal status already belongs in the card head. A red exception
      // disclosure made cancelled and stopped work look active again.
      const card = workItemCard(documentNode, row, scope, {
        tone: "done",
        timestamp: finishedAt(row),
        timeLabel: "finished",
      });
      appendItemDelivery(documentNode, card, row, deployments);
      return withClaimants(card, row);
    });
    if (done.length > visible.length) visible.push(seeMoreCard(documentNode, scope));
    bands.done.setCount(done.length);
    bands.done.renderCards(visible, "Nothing finished in the last 24 hours.");
  };
  paint();
  return paint;
}
