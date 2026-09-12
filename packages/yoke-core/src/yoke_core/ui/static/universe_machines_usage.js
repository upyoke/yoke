import {
  summarizeSessionUsage,
  usageSummaryCostDisplay,
  usageSummaryLabel,
  usageSummaryScope,
  usageSummaryTokenDisplay,
} from "./session_usage_display.js";
import { appendUsageStats } from "./universe_usage_stats.js";
import { callFunction, el } from "./universe_view_support.js";

/**
 * The sessions this machine's 24-hour figures answer for, scoped to
 * `projects` (every visible project when empty) — not just a loaded page.
 *
 * The engine's cohort is the union of sessions that ended inside the window
 * and sessions that started inside it and have not ended, each counted once,
 * so a machine that is busy right now reads as busy instead of waiting for
 * its sessions to end. A machine tile sums that durable read rather than
 * whatever rows a roster happens to have on screen, so the total answers for
 * the whole window regardless of paging or filters. Rows carry the same
 * derived usage fields the live roster already hands a card, keyed by
 * `machine_id` so `appendMachineUsage` can filter and sum them.
 */
export async function fetchRecentUsageRows(context, projects = []) {
  const payload = { usage_last_24h: true };
  if (projects.length) payload.projects = projects;
  const result = await callFunction(context.client, "sessions.list", payload);
  if (!result.envelope.success) throw result;
  return result.envelope.result?.rows || [];
}

/**
 * What this machine's sessions spent in the last 24 hours.
 *
 * Each metric label carries the window itself — `24H TOKENS`, `24H API COST`,
 * `24H SESSIONS` — so the figures state their own scope where they are read,
 * with no separate heading above them to pair up by position. The SESSIONS
 * figure names how many contributing sessions underlie the total — a single
 * count, not a ratio, since its job is to say what the numbers beside it
 * answer for. The tokens and cost figures are the machine's own rollup rather
 * than one session's reading, so unlike a session card they carry no trailing
 * approximation mark; the tooltip still names the priced count when it trails
 * the session count, since a session on an unpriced model contributes tokens
 * but nothing to the dollar figure.
 */
export function appendMachineUsage(documentNode, card, relay, sessions) {
  const rows = (Array.isArray(sessions) ? sessions : []).filter(
    (row) => row && row.machine_id && row.machine_id === relay.machine_id,
  );
  if (!rows.length) return;
  const summary = summarizeSessionUsage(rows);
  const tooltip = [
    usageSummaryScope(summary),
    "estimated API-equivalent cost for this machine's sessions in the last "
    + "24 hours — those that ended in the window and those still running "
    + "that started in it — not consumption of any subscription plan; the "
    + "dollar total covers only the sessions that could be priced",
  ].filter(Boolean).join(". ");
  const block = el(documentNode, "div", "machine-usage-block");
  card.appendChild(block);
  if (!summary.covered) {
    const line = el(documentNode, "div", "machine-usage usage-stats");
    const stat = el(documentNode, "div", "usage-stat");
    stat.appendChild(el(
      documentNode, "span", "usage-stat-unit", usageSummaryLabel(summary),
    ));
    line.appendChild(stat);
    block.appendChild(line);
    return;
  }
  appendUsageStats(documentNode, block, {
    className: "machine-usage usage-stats",
    tooltip,
    stats: [
      {
        fact: "tokens",
        value: usageSummaryTokenDisplay(summary),
        unit: "24h tokens",
        partial: summary.partial,
      },
      {
        fact: "cost",
        value: usageSummaryCostDisplay(summary),
        unit: "24h API cost",
        partial: summary.partial,
      },
      {
        fact: "coverage",
        value: String(summary.covered),
        unit: "24h sessions",
      },
    ],
  });
}
