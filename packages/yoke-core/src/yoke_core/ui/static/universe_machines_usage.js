import {
  summarizeSessionUsage,
  usageSummaryCostDisplay,
  usageSummaryLabel,
  usageSummaryScope,
  usageSummaryTokenDisplay,
} from "./session_usage_display.js";
import { appendUsageStats } from "./universe_usage_stats.js";
import { callFunction, el } from "./universe_view_support.js";

//: The window label the tile shows, matching the durable read's own scope
//: (`sessions.list` with `ended_last_24h: true`) — a machine tile answers
//: for every session that ended in that window, never for a loaded page.
const ENDED_WINDOW_LABEL = "Ended in last 24h";

/**
 * Every session that ended on this machine in the trailing 24 hours,
 * scoped to `projects` (every visible project when empty) — not just a
 * loaded page.
 *
 * A machine tile sums a durable read rather than whatever rows a roster
 * happens to have on screen, so the total answers for the whole window
 * regardless of paging or filters. Rows carry the same derived usage
 * fields the live roster already hands a card, keyed by `machine_id` so
 * `appendMachineUsage` can filter and sum them exactly as before.
 */
export async function fetchEndedUsageRows(context, projects = []) {
  const payload = { ended_last_24h: true };
  if (projects.length) payload.projects = projects;
  const result = await callFunction(context.client, "sessions.list", payload);
  if (!result.envelope.success) throw result;
  return result.envelope.result?.rows || [];
}

/**
 * What sessions that ended on this machine in the last 24 hours spent.
 *
 * The SESSIONS column names how many contributing sessions underlie the
 * total — a single count, not a ratio, since the tile's job is to say
 * what the numbers beside it answer for. The tokens and cost figures are
 * the machine's own rollup rather than one session's reading, so unlike
 * a session card they carry no trailing approximation mark; the tooltip
 * still names the priced count when it trails the session count, since a
 * session on an unpriced model contributes tokens but nothing to the
 * dollar figure.
 */
export function appendMachineUsage(documentNode, card, relay, sessions) {
  const rows = (Array.isArray(sessions) ? sessions : []).filter(
    (row) => row && row.machine_id && row.machine_id === relay.machine_id,
  );
  if (!rows.length) return;
  const summary = summarizeSessionUsage(rows);
  const tooltip = [
    usageSummaryScope(summary),
    "estimated API-equivalent cost for sessions that ended on this machine "
    + "in the last 24 hours, not consumption of any subscription plan; the "
    + "dollar total covers only the sessions that could be priced",
  ].filter(Boolean).join(". ");
  const block = el(documentNode, "div", "machine-usage-block");
  block.appendChild(el(
    documentNode, "span", "machine-usage-window", ENDED_WINDOW_LABEL,
  ));
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
        unit: "tokens",
        partial: summary.partial,
      },
      {
        fact: "cost",
        value: usageSummaryCostDisplay(summary),
        unit: "API cost",
        partial: summary.partial,
      },
      {
        fact: "coverage",
        value: String(summary.covered),
        unit: "sessions",
      },
    ],
  });
}
