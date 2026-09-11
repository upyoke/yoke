import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";

/**
 * One padded statistics row: a value stacked on the word that names it.
 * Session cards and machine tiles share this so tokens and API cost cannot
 * drift into unlabeled inline figures on one page and labeled columns on
 * another.
 */
export function appendUsageStats(documentNode, parent, {
  className, stats, tooltip,
}) {
  const row = el(documentNode, "div", className);
  for (const stat of (Array.isArray(stats) ? stats : [])) {
    const node = el(
      documentNode,
      "div",
      stat.partial ? "usage-stat is-partial" : "usage-stat",
    );
    if (stat.fact) node.setAttribute("data-usage-fact", stat.fact);
    node.appendChild(el(documentNode, "span", "usage-stat-value", stat.value));
    node.appendChild(el(documentNode, "span", "usage-stat-unit", stat.unit));
    row.appendChild(node);
  }
  if (tooltip) attachTooltip(documentNode, row, tooltip);
  parent.appendChild(row);
  return row;
}
