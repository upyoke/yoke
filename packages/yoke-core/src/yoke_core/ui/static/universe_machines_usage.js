import {
  summarizeSessionUsage,
  usageSummaryCostDisplay,
  usageSummaryLabel,
  usageSummaryScope,
  usageSummaryTokenDisplay,
} from "./session_usage_display.js";
import { appendUsageStats } from "./universe_usage_stats.js";
import { el } from "./universe_view_support.js";

/**
 * What the sessions on this page have spent on this machine.
 *
 * A machine tile sums the rows currently represented — the ones the
 * roster is showing, after whatever filters are applied — and never the
 * machine's whole history, which nothing here has read. That scope is a
 * labeled column rather than trailing unlabeled prose, because a sum
 * whose membership is unstated invites being read as a lifetime figure.
 *
 * The SESSIONS column names how many of those rows actually contributed
 * to the total — a single count, not a ratio, since the tile's job is
 * to say what underlies the numbers beside it, not to audit the roster.
 * The tokens and cost figures are the machine's own rollup rather than
 * one session's reading, so unlike a session card they carry no trailing
 * approximation mark; the tooltip still names the priced count when it
 * trails the session count, since a session on an unpriced model
 * contributes tokens but nothing to the dollar figure.
 */
export function appendMachineUsage(documentNode, card, relay, sessions) {
  const rows = (Array.isArray(sessions) ? sessions : []).filter(
    (row) => row && row.machine_id && row.machine_id === relay.machine_id,
  );
  if (!rows.length) return;
  const summary = summarizeSessionUsage(rows);
  const tooltip = [
    usageSummaryScope(summary),
    "estimated API-equivalent cost for the sessions shown here, "
    + "not consumption of any subscription plan; the dollar total covers "
    + "only the sessions that could be priced",
  ].filter(Boolean).join(". ");
  if (!summary.covered) {
    const line = el(documentNode, "div", "machine-usage usage-stats");
    const stat = el(documentNode, "div", "usage-stat");
    stat.appendChild(el(
      documentNode, "span", "usage-stat-unit", usageSummaryLabel(summary),
    ));
    line.appendChild(stat);
    card.appendChild(line);
    return;
  }
  appendUsageStats(documentNode, card, {
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
