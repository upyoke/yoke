import { attachTooltip } from "./universe_tooltip.js";
import { el } from "./universe_view_support.js";

/**
 * One statistics row whose caller owns the final layout. Session cards and
 * machine tiles share the value/unit pairs so tokens and cost cannot drift
 * into unlabeled figures on one page and labeled figures on another.
 */
/**
 * One value/unit tile.
 *
 * Exported on its own so a row that is not built here — the Sessions
 * roster's five facts, three of which are counts rather than usage — can
 * append the same tile as a direct sibling instead of nesting a second row
 * inside the first and breaking the grid the five share.
 */
export function usageStatTile(documentNode, stat) {
  const node = el(
    documentNode,
    "div",
    stat.partial ? "usage-stat is-partial" : "usage-stat",
  );
  if (stat.fact) node.setAttribute("data-usage-fact", stat.fact);
  node.appendChild(el(documentNode, "span", "usage-stat-value", stat.value));
  node.appendChild(el(documentNode, "span", "usage-stat-unit", stat.unit));
  return node;
}

export function appendUsageStats(documentNode, parent, {
  className, stats, tooltip,
}) {
  const row = el(documentNode, "div", className);
  for (const stat of (Array.isArray(stats) ? stats : [])) {
    row.appendChild(usageStatTile(documentNode, stat));
  }
  if (tooltip) attachTooltip(documentNode, row, tooltip);
  parent.appendChild(row);
  return row;
}
