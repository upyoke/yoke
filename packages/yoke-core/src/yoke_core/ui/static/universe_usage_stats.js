import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";

/**
 * One statistics row whose caller owns the final layout. Session cards and
 * machine tiles share the value/unit pairs so tokens and cost cannot drift
 * into unlabeled figures on one page and labeled figures on another.
 */
export function appendUsageStats(documentNode, parent, {
  className, leading = null, stats, tooltip,
}) {
  const row = el(documentNode, "div", className);
  if (leading) row.appendChild(leading);
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
