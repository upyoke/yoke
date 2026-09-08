import {
  sessionCostDisplay,
  sessionTokensDisplay,
  sessionUsageIsPartial,
} from "./session_usage_display.js";
import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";

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
  const line = el(documentNode, "div", "session-usage-line");
  line.appendChild(el(documentNode, "span", "session-usage-label", "usage"));
  const usageClass = sessionUsageIsPartial(row)
    ? "session-usage is-partial"
    : "session-usage";
  const tokens = el(
    documentNode, "span", usageClass, sessionTokensDisplay(row),
  );
  tokens.setAttribute("data-usage-fact", "tokens");
  line.appendChild(tokens);
  line.appendChild(el(documentNode, "span", "session-usage-unit", "tokens"));
  const cost = el(
    documentNode,
    "span",
    `${usageClass} session-usage-cost`,
    sessionCostDisplay(row),
  );
  cost.setAttribute("data-usage-fact", "cost");
  line.appendChild(cost);
  line.appendChild(el(
    documentNode, "span", "session-usage-unit", "API cost",
  ));
  attachTooltip(
    documentNode, line,
    row.usage_note || "no consumption recorded for this session yet",
  );
  body.appendChild(line);
}
