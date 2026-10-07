// The Frontier's Waiting band as a graph of unsatisfied dependencies.
// Columns are "holding work up" and then steps behind, so a column only exists
// when something sits in it. Lines are uniform except the longest chain;
// tiles and the detail panel name each gate and condition, and anything that
// cannot move on its own is drawn red on its own tile. On a phone the canvas
// gives way to an outline of each chain.

import {
  frontierColumnHeading,
  frontierColumnPlan,
  frontierGraphColumns,
  frontierOutline,
} from "./frontier_dependency_model.js";
import { frontierEdgeLayer } from "./frontier_graph_edges.js";
import { frontierDetail, frontierTile } from "./frontier_graph_tiles.js";
import { el } from "./universe_view_support.js";

function isTileKey(event) {
  return event.key === "Enter" || event.key === " ";
}

// Clicks on the item number navigate and clicks on the session chip open the
// session card; neither selects the tile.
function selectsTile(event) {
  return !event.target?.closest?.("a, .item-claimant");
}

/**
 * The graph section for a model that has at least one edge.
 *
 * `helpers` supplies `claimantFor(ref)` and `cardFor(ref)`, so the graph
 * draws production's own session chip and card rather than copies of them.
 */
export function frontierGraphSection(documentNode, model, helpers) {
  const section = el(documentNode, "section", "fdv-graph");
  const layout = el(documentNode, "div", "fdv-graph-layout");
  const canvas = el(documentNode, "div", "fdv-graph-canvas");
  const grid = el(documentNode, "div", "fdv-graph-grid");
  const detail = el(documentNode, "aside", "fdv-graph-detail");
  const tiles = new Map();
  const gridTiles = new Map();
  const stacks = new Map();
  let interact = null;

  const tile = (ref, inGrid) => {
    const node = frontierTile(documentNode, model, ref, helpers);
    if (!tiles.has(ref)) tiles.set(ref, []);
    tiles.get(ref).push(node);
    if (inGrid) gridTiles.set(ref, node);
    node.addEventListener("click", (event) => {
      if (selectsTile(event)) interact.select(ref);
    });
    node.addEventListener("keydown", (event) => {
      if (!isTileKey(event) || event.target !== node) return;
      event.preventDefault();
      interact.select(ref);
    });
    node.addEventListener("pointerenter", () => interact.hover(ref));
    node.addEventListener("focus", () => interact.hover(ref));
    return node;
  };

  const cols = frontierGraphColumns(model);
  grid.style.setProperty("--fdv-cols", String(cols.length));
  cols.forEach((col, c) => {
    const column = el(documentNode, "div", "fdv-graph-col");
    column.appendChild(el(documentNode, "div", "fdv-graph-col-head", frontierColumnHeading(c)));
    for (const entry of frontierColumnPlan(col.filter((n) => !n.cycle))) {
      if (entry.kind === "tile") {
        column.appendChild(tile(entry.ref, true));
        continue;
      }
      const stack = el(documentNode, "button", "fdv-stack");
      stack.type = "button";
      stack.setAttribute("data-fdv-stack", entry.refs.join(" "));
      stack.appendChild(el(documentNode, "strong", "", `+${entry.refs.length} more`));
      stack.appendChild(el(documentNode, "span", "", entry.phrase));
      const hidden = el(documentNode, "div", "fdv-stack-items");
      hidden.hidden = true;
      for (const ref of entry.refs) {
        hidden.appendChild(tile(ref, true));
        stacks.set(ref, stack);
      }
      // Expanding replaces the stack with its items in place.
      stack.addEventListener("click", () => {
        hidden.hidden = false;
        stack.parentNode?.removeChild(stack);
        for (const ref of entry.refs) stacks.delete(ref);
        setTimeout(interact.redraw);
      });
      column.appendChild(stack);
      column.appendChild(hidden);
    }
    const loop = col.filter((n) => n.cycle);
    if (loop.length) {
      column.appendChild(el(documentNode, "div", "fdv-graph-divider is-stuck", "Deadlocked"));
      for (const n of loop) column.appendChild(tile(n.ref, true));
    }
    grid.appendChild(column);
  });
  canvas.appendChild(grid);
  layout.appendChild(canvas);
  layout.appendChild(detail);

  const outline = el(documentNode, "div", "fdv-graph-outline");
  const branch = ({ ref, children }) => {
    const li = el(documentNode, "li");
    li.appendChild(tile(ref, false));
    if (children.length) {
      const ul = el(documentNode, "ul");
      for (const child of children) ul.appendChild(branch(child));
      li.appendChild(ul);
    }
    return li;
  };
  for (const tree of frontierOutline(model)) {
    const ul = el(documentNode, "ul", "fdv-outline");
    ul.appendChild(branch(tree));
    outline.appendChild(ul);
  }
  section.appendChild(layout);
  section.appendChild(outline);

  // An item folded into a stack draws its edges to the stack.
  const locate = (ref) => stacks.get(ref) || gridTiles.get(ref);
  const edges = frontierEdgeLayer(documentNode, canvas, grid, model, locate);
  interact = frontierGraphInteraction(documentNode, model, {
    section, layout, detail, tiles, edges, helpers,
  });
  section.addEventListener("pointerleave", () => interact.hover(null));
  return section;
}

// Hovering or focusing a tile lights its whole lineage; clicking pins it and
// opens the detail panel; clicking it again, or Close, unpins.
function frontierGraphInteraction(documentNode, model, parts) {
  const { section, layout, detail, tiles, edges, helpers } = parts;
  let pinned = null;
  const light = (ref) => {
    const lit = ref ? model.lineage(ref) : null;
    section.classList.toggle("has-focus", Boolean(lit));
    for (const [tileRef, nodes] of tiles) {
      for (const node of nodes) {
        node.classList.toggle("is-lit", Boolean(lit) && lit.has(tileRef));
        node.classList.toggle("is-selected", tileRef === pinned);
      }
    }
    for (const path of edges.paths) {
      const on = Boolean(lit) && lit.has(path.getAttribute("data-from"))
        && lit.has(path.getAttribute("data-to"));
      path.classList.toggle("is-lit", on);
    }
  };
  const select = (ref) => {
    pinned = pinned === ref ? null : ref;
    light(pinned);
    layout.classList.toggle("has-detail", Boolean(pinned));
    setTimeout(edges.draw);
    if (!pinned) {
      detail.replaceChildren();
      return;
    }
    const close = el(documentNode, "button", "fdv-lane-jump", "Close ×");
    close.type = "button";
    close.addEventListener("click", () => select(pinned));
    detail.replaceChildren(close, ...frontierDetail(documentNode, model, pinned, helpers, select));
    detail.scrollIntoView?.({ block: "nearest" });
  };
  return {
    select,
    hover: (ref) => { if (!pinned) light(ref); },
    redraw: edges.draw,
    pinned: () => pinned,
  };
}

export function frontierGraphEmpty(documentNode) {
  return el(documentNode, "p", "work-band-empty", "Nothing is waiting on other work.");
}
