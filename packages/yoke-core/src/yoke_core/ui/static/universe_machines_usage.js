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
 * Coverage is stated for the same reason. Sessions on a harness that
 * counts no tokens contribute nothing, so "2 of 5 sessions reported" is
 * the difference between a machine that spent little and one whose
 * spending is mostly unmeasured. The dollar total has its own coverage:
 * a session whose model carries no researched price reports tokens and
 * no cost, so the scope names the priced count separately when the two
 * differ rather than letting one count answer for both.
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
        value: `${summary.covered} of ${summary.total}`,
        unit: "sessions reported",
      },
    ],
  });
}
