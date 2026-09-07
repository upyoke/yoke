import {
  summarizeSessionUsage,
  usageSummaryLabel,
  usageSummaryScope,
} from "./session_usage_display.js";
import { el } from "./universe_view_support.js";

/**
 * What the sessions on this page have spent on this machine.
 *
 * A machine tile sums the rows currently represented — the ones the
 * roster is showing, after whatever filters are applied — and never the
 * machine's whole history, which nothing here has read. That scope is
 * drawn beside the total rather than left implied, because a sum whose
 * membership is unstated invites being read as a lifetime figure.
 *
 * Coverage is stated for the same reason. Sessions on a harness that
 * counts no tokens contribute nothing, so "2 of 5 sessions reported" is
 * the difference between a machine that spent little and one whose
 * spending is mostly unmeasured.
 */
export function appendMachineUsage(documentNode, card, relay, sessions) {
  const rows = (Array.isArray(sessions) ? sessions : []).filter(
    (row) => row && row.machine_id && row.machine_id === relay.machine_id,
  );
  if (!rows.length) return;
  const summary = summarizeSessionUsage(rows);
  const line = el(documentNode, "div", "machine-usage");
  line.appendChild(el(
    documentNode,
    "span",
    summary.partial ? "machine-usage-total is-partial" : "machine-usage-total",
    usageSummaryLabel(summary) || "—",
  ));
  const scope = el(
    documentNode, "span", "machine-usage-scope", usageSummaryScope(summary),
  );
  scope.title =
    "estimated API-equivalent cost for the sessions shown here, "
    + "not consumption of any subscription plan";
  line.appendChild(scope);
  card.appendChild(line);
}
