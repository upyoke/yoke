import {
  sessionCostDisplay,
  sessionTokensDisplay,
  sessionUsageIsPartial,
} from "./session_usage_display.js";
import { appendUsageStats } from "./universe_usage_stats.js";

/**
 * What this session has spent, beside what the same tokens would have cost
 * at API list prices.
 *
 * Each figure names what it is. The line used to read `44m · $34` and left a
 * reader to guess which number was which, on the theory that the card had
 * room for two short values and not for the sentence that keeps an
 * API-equivalent figure from reading as consumption of a subscription plan.
 * The units are short enough to carry that themselves; the sentence — where
 * the prices came from, when they were checked, and why either figure is
 * partial — is what the line's explanation still carries.
 */
export function appendSessionUsage(documentNode, body, row) {
  const partial = sessionUsageIsPartial(row);
  appendUsageStats(documentNode, body, {
    className: "session-usage-line usage-stats",
    tooltip: row.usage_note || "no consumption recorded for this session yet",
    stats: [
      {
        fact: "tokens",
        value: sessionTokensDisplay(row),
        unit: "tokens",
        partial,
      },
      {
        fact: "cost",
        value: sessionCostDisplay(row),
        unit: "API cost",
        partial,
      },
    ],
  });
}
