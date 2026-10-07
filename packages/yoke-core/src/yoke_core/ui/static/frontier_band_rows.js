// Which Frontier band each item belongs to, decided once from one item
// roster, one frontier read and one session roster. An item lands in exactly
// one of Waiting, Ready, Active, Release and Done.
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

import {
  claimantsByItemRef,
  claimedItemRefs,
  isQualifyingClaimant,
} from "./universe_item_claimant.js";

const RELEASE_STATE = "release";
const LIVE_SESSION_STATES = new Set(["active", "stale"]);

export function reference(row) {
  return String(row.public_ref || "");
}

function status(row) {
  return String(row.status || "").toLowerCase();
}

export function enabled(value) {
  return value === true || value === 1 || value === "1" || value === "true";
}

const newestFirst = (key) => (left, right) => String(right[key] || "")
  .localeCompare(String(left[key] || ""));

// The items an item's blocked rows name, from the rows' own blocking_item
// field. A pill names them; the reason text is never parsed for them.
function dependencyLabel(blockers) {
  return blockers.length === 1
    ? `Waiting for ${blockers[0]}`
    : `Waiting for ${blockers.length} items`;
}

export function waitingReason(row, blockedRows = []) {
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
        text: row.blocked_reason || blockedRows[0]?.why || "Blocked without a reason.",
        tone: "blocked",
      },
    };
  }
  if (!blockedRows.length) return null;
  const blockers = [...new Set(blockedRows.map((entry) => entry.blocking_item).filter(Boolean))];
  const text = blockedRows.map((entry) => entry.why).filter(Boolean).join(" ")
    || "An upstream fact is unsatisfied.";
  // A wait with no blocking item is the scheduler holding the item for a
  // reason of its own (an incomplete idea body, a defended prior owner): it
  // is held, not waiting on other work.
  if (!blockers.length) {
    return { rank: 1, flag: { label: "Held", text, tone: "blocked" } };
  }
  return {
    rank: 2,
    flag: { label: dependencyLabel(blockers), text, tone: "dependency" },
  };
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
    tone: "owner-unavailable",
  },
};

// When the item finished, as opposed to when its code landed. The feed dates
// this from the lifecycle transition that put the item into the status it
// holds, and leaves it absent for anything that has not finished.
export function finishedAt(row) {
  return row.finished_at || "";
}

// The feed resolves both facts against the item's own pinned workflow
// definition, so the band never re-derives them from a status list.
function recentlyDone(row) {
  return Boolean(row.finished) && Boolean(finishedAt(row));
}

function liveSessions(rows) {
  return rows.filter((row) => (
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

/**
 * Every band's rows, in display order, from unscoped reads.
 *
 * The bands are computed before any project filter, because the filter keeps
 * whole dependency chains: an item outside the selected projects stays when
 * a chain ties it to one.
 */
export function frontierBandRows({ items, readyRows, blockedRows, sessionRows }) {
  const itemsByRef = new Map(items.map((row) => [reference(row), row]));
  const blockedByRef = new Map();
  for (const row of blockedRows) {
    const ref = reference(row);
    if (!blockedByRef.has(ref)) blockedByRef.set(ref, []);
    blockedByRef.get(ref).push(row);
  }
  const sessions = liveSessions(sessionRows);
  const qualifying = sessions.filter(isQualifyingClaimant);
  const claimants = claimantsByItemRef(qualifying);
  const heldByAnyLiveSession = new Set(sessions.flatMap(claimedItemRefs));

  const releasing = items
    .filter((row) => status(row) === RELEASE_STATE)
    .sort(newestFirst("updated_at"));
  const releasingRefs = new Set(releasing.map(reference));
  const live = items.filter((row) => (
    !row.terminal && !releasingRefs.has(reference(row))
  ));
  // Active first, because being worked on is the stronger fact: a blocked
  // item somebody is actively unblocking belongs where the work is, with
  // its reason still on the card.
  const active = live
    .filter((row) => !enabled(row.frozen) && claimants.has(reference(row)))
    .sort(newestFirst("updated_at"))
    .map((row) => ({ row, reason: waitingReason(row, blockedByRef.get(reference(row))) }));
  const activeRefs = new Set(active.map(({ row }) => reference(row)));

  // Only what stops an item starting makes it wait. An edge that holds back
  // its merge or close leaves it free to build, so it stays where its work
  // is and the graph draws the edge.
  const waiting = live
    .filter((row) => !activeRefs.has(reference(row)))
    .map((row) => {
      const ref = reference(row);
      const starting = (blockedByRef.get(ref) || []).filter(
        (entry) => !entry.gate_point || entry.gate_point === "activation",
      );
      const reason = waitingReason(row, starting)
        || (heldByAnyLiveSession.has(ref) ? UNAVAILABLE_OWNER : null);
      return { row, reason };
    })
    .filter((entry) => entry.reason)
    .sort((left, right) => (
      left.reason.rank - right.reason.rank
      || newestFirst("updated_at")(left.row, right.row)
    ));
  const waitingRefs = new Set(waiting.map((entry) => reference(entry.row)));

  const ready = readyRows
    .map((row) => ({ ...(itemsByRef.get(reference(row)) || {}), ...row }))
    .filter((row) => {
      const ref = reference(row);
      return !releasingRefs.has(ref) && !waitingRefs.has(ref)
        && !activeRefs.has(ref) && !heldByAnyLiveSession.has(ref);
    });

  const done = items
    .filter(recentlyDone)
    .sort((left, right) => finishedAt(right).localeCompare(finishedAt(left)));

  return {
    waiting,
    ready,
    active,
    releasing,
    done,
    claimants,
    stages: stagesByItemRef(qualifying),
  };
}
