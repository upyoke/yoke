// The lines of the Frontier's Waiting graph: one SVG path per unsatisfied
// edge, in a layer under the tiles, redrawn whenever the canvas resizes or
// scrolls. Every line looks the same except the longest chain; the gate and
// condition live on the tiles and in the detail panel, never in line style.

const SVG = "http://www.w3.org/2000/svg";

function hasLayout(node) {
  return typeof node?.getBoundingClientRect === "function"
    && typeof node.getClientRects === "function"
    && node.getClientRects().length > 0;
}

/**
 * Lay the edge layer into `canvas` behind `grid`.
 *
 * `locate(ref)` answers the element an edge end attaches to: the item's own
 * tile, or the stack it is folded into. Paths exist from the start, so their
 * count and emphasis are facts of the DOM; `draw` only places them.
 */
export function frontierEdgeLayer(documentNode, canvas, grid, model, locate) {
  const svg = documentNode.createElementNS(SVG, "svg");
  svg.classList.add("fdv-edges");
  svg.setAttribute("aria-hidden", "true");
  const paths = model.edges.map((edge) => {
    const path = documentNode.createElementNS(SVG, "path");
    const critical = model.critical.has(edge.from) && model.critical.has(edge.to);
    path.classList.add("fdv-edge");
    if (critical) path.classList.add("is-critical");
    path.setAttribute("data-from", edge.from);
    path.setAttribute("data-to", edge.to);
    svg.appendChild(path);
    return { edge, path };
  });
  canvas.insertBefore(svg, canvas.children?.[0] || null);

  const draw = () => {
    if (!hasLayout(canvas)) return;
    const box = canvas.getBoundingClientRect();
    // Sized to the content, never to the scroll area: an edge layer taller
    // than the canvas would give it a vertical scroll of its own.
    svg.setAttribute("width", grid.scrollWidth + grid.offsetLeft);
    svg.setAttribute("height", grid.offsetHeight + grid.offsetTop);
    const ox = canvas.scrollLeft - box.left;
    const oy = canvas.scrollTop - box.top;
    for (const { edge, path } of paths) {
      const a = locate(edge.from);
      const b = locate(edge.to);
      if (!hasLayout(a) || !hasLayout(b)) {
        path.setAttribute("d", "");
        continue;
      }
      let ra = a.getBoundingClientRect();
      let rb = b.getBoundingClientRect();
      if (rb.left >= ra.right - 4 || ra.left >= rb.right - 4) {
        if (ra.left > rb.left) [ra, rb] = [rb, ra];
        const x1 = ra.right + ox, y1 = ra.top + ra.height / 2 + oy;
        const x2 = rb.left + ox, y2 = rb.top + rb.height / 2 + oy;
        const bend = Math.max(24, (x2 - x1) / 2);
        path.setAttribute("d", `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`);
      } else {
        // Same column (a cycle): bracket on the right.
        const x1 = ra.right + ox, y1 = ra.top + ra.height / 2 + oy;
        const x2 = rb.right + ox, y2 = rb.top + rb.height / 2 + oy;
        const reach = Math.min(40, 14 + Math.abs(y2 - y1) / 10);
        path.setAttribute("d", `M${x1},${y1} C${x1 + reach},${y1} ${x2 + reach},${y2} ${x2},${y2}`);
      }
    }
  };
  // First draw on a timer: animation frames and resize observations pause
  // while the page is in a background tab, timers do not.
  if (typeof ResizeObserver === "function") new ResizeObserver(draw).observe(canvas);
  canvas.addEventListener("scroll", draw, { passive: true });
  setTimeout(draw);
  return { paths: paths.map(({ path }) => path), draw };
}
