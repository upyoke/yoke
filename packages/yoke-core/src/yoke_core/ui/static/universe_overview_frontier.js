// Waiting, Ready, and Done are filters over the same item roster. Frontier is
// authoritative for runnable work and dependency reasons; the item overview
// supplies frozen/blocked flags plus terminal timestamps.

import { buildUniverseRoute } from "./universe_navigation.js";
import { overviewItemCard } from "./universe_overview_cards.js";
import {
  callError,
  OVERVIEW_CARD_LIMIT,
  rowsInOverviewScope,
  successfulResult,
} from "./universe_overview_primitives.js";
import { el, settledScopedCalls } from "./universe_view_support.js";

const TERMINAL_STATES = new Set(["done", "cancelled", "stopped"]);
const DONE_WINDOW_MS = 24 * 60 * 60 * 1000;

function reference(row) {
  return String(row.public_ref || row.item_id || row.id || "");
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

function completedAt(row) {
  return row.merged_at || row.updated_at || row.created_at;
}

function recentlyDone(row, now = Date.now()) {
  if (!TERMINAL_STATES.has(String(row.status || "").toLowerCase())) return false;
  const timestamp = new Date(completedAt(row)).getTime();
  return Number.isFinite(timestamp) && now - timestamp <= DONE_WINDOW_MS;
}

function mergeItemFacts(row, itemsByRef) {
  return { ...(itemsByRef.get(reference(row)) || {}), ...row };
}

function moreDoneCard(documentNode, hiddenCount, scope) {
  const card = el(documentNode, "a", "overview-item-card overview-more-card");
  card.href = buildUniverseRoute(
    "items", scope === "all" ? null : scope.join(","),
  );
  card.appendChild(el(
    documentNode, "strong", "overview-more-count", `+${hiddenCount}`,
  ));
  card.appendChild(el(
    documentNode, "span", null, "more finished in this window",
  ));
  return card;
}

export async function loadFrontier(context, bands, getScope) {
  const { callResults } = await settledScopedCalls(context, [
    { functionId: "items.overview.list", payload: {} },
    { functionId: "frontier.list", payload: {} },
  ]);
  if (!context.isMounted()) return null;
  const paint = () => {
    const itemsResult = successfulResult(callResults[0]);
    const frontierResult = successfulResult(callResults[1]);
    if (!itemsResult || !frontierResult) {
      const failed = !itemsResult ? callResults[0] : callResults[1];
      const message = callError(failed, "Frontier could not be loaded.");
      for (const band of Object.values(bands)) band.renderError(message);
      return;
    }
    const scope = getScope();
    const projects = context.projects();
    const items = rowsInOverviewScope(
      itemsResult.rows || [], scope, projects,
    );
    const readyRows = rowsInOverviewScope(
      frontierResult.ready_rows || [], scope, projects,
    );
    const blockedRows = rowsInOverviewScope(
      frontierResult.blocked_rows || [], scope, projects,
    );
    const itemsByRef = new Map(items.map((row) => [reference(row), row]));
    const blockedByRef = new Map(
      blockedRows.map((row) => [reference(row), row]),
    );

    const waiting = items
      .filter((row) => !TERMINAL_STATES.has(String(row.status || "").toLowerCase()))
      .map((row) => ({ row, reason: waitingReason(row, blockedByRef.get(reference(row))) }))
      .filter((entry) => entry.reason)
      .sort((left, right) => (
        left.reason.rank - right.reason.rank
        || String(right.row.updated_at || "").localeCompare(
          String(left.row.updated_at || ""),
        )
      ));
    bands.waiting.setCount(waiting.length);
    bands.waiting.renderCards(waiting.map(({ row, reason }) => overviewItemCard(
      context.document,
      row,
      scope,
      { flag: reason.flag, meta: "waiting", timestamp: row.created_at, timeLabel: "filed" },
    )), "Nothing is stopped.");

    const ready = readyRows
      .map((row) => mergeItemFacts(row, itemsByRef))
      .filter((row) => !waiting.some((entry) => reference(entry.row) === reference(row)));
    bands.ready.setCount(ready.length);
    bands.ready.renderCards(ready.map((row) => overviewItemCard(
      context.document,
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

    const done = items
      .filter((row) => recentlyDone(row))
      .sort((left, right) => String(completedAt(right)).localeCompare(
        String(completedAt(left)),
      ));
    const visible = done.slice(0, OVERVIEW_CARD_LIMIT).map((row) => {
      const cancelled = String(row.status || "").toLowerCase() !== "done";
      const deployed = String(row.deployed_to || "").trim();
      return overviewItemCard(context.document, row, scope, {
        tone: cancelled ? "cancelled" : "done",
        flag: {
          label: cancelled ? "Stopped" : "Complete",
          text: cancelled
            ? (row.blocked_reason || "This work did not land.")
            : (deployed ? `Merged and deployed to ${deployed}.` : "Merged."),
          tone: cancelled ? "blocked" : "done",
        },
        meta: row.status,
        timestamp: completedAt(row),
        timeLabel: "finished",
      });
    });
    if (done.length > visible.length) {
      visible.push(moreDoneCard(
        context.document, done.length - visible.length, scope,
      ));
    }
    bands.done.setCount(done.length);
    bands.done.renderCards(visible, "Nothing finished in the last 24 hours.");
  };
  paint();
  return paint;
}
