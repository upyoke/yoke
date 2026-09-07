import {
  sessionCostDisplay,
  sessionTokensDisplay,
  sessionUsageIsPartial,
} from "./session_usage_display.js";
import { el } from "./universe_view_support.js";

/**
 * What this session has spent, beside what the same tokens would have cost
 * at API list prices.
 *
 * The estimate is titled rather than labelled in place: the card has room
 * for two short values, not for the sentence that keeps an API-equivalent
 * figure from reading as consumption of a subscription plan. The title
 * carries that sentence along with where the prices came from, when they
 * were checked, and why either figure is partial.
 */
export function appendSessionUsage(documentNode, body, row) {
  const line = el(documentNode, "div", "session-usage-line");
  line.title = row.usage_note || "no consumption recorded for this session yet";
  const usageClass = sessionUsageIsPartial(row)
    ? "session-usage is-partial"
    : "session-usage";
  const tokens = el(
    documentNode, "span", usageClass, sessionTokensDisplay(row),
  );
  tokens.setAttribute("data-usage-fact", "tokens");
  line.appendChild(tokens);
  const cost = el(
    documentNode,
    "span",
    `${usageClass} session-usage-cost`,
    sessionCostDisplay(row),
  );
  cost.setAttribute("data-usage-fact", "cost");
  line.appendChild(cost);
  body.appendChild(line);
}
