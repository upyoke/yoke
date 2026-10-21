/* Navigation and relationship tracing share the map's node model. */
let hovered = null, showConnections = false;
function rootOf(node) {
  while (node?.parent) node = byId.get(node.parent);
  return node;
}
function updateSourceList() {
  const list = document.querySelector('#source-list');
  list.replaceChildren();
  const overview = text('button', 'Overview', !focus ? 'active overview' : 'overview');
  overview.onclick = home;
  list.append(overview);
  roots.forEach(node => {
    const button = text('button', '', rootOf(focus) === node ? 'active' : '');
    const dot = text('span', '', 'source-dot');
    dot.style.background = node.color;
    button.append(dot, text('span', node.title));
    button.onclick = () => choose(node);
    list.append(button);
  });
}
function updateConnections() {
  hovered = null;
  const panel = document.querySelector('#connections');
  panel.replaceChildren();
  const links = [], seen = new Set();
  if (focus) {
    for (let node = focus; node; node = byId.get(node.parent)) {
      for (const edge of node.connections || []) {
        if (seen.has(edge.target)) continue;
        seen.add(edge.target);
        links.push({...edge, direction: 'Continue to'});
      }
    }
    byId.forEach(node => {
      for (const edge of node.connections || []) {
        if (edge.target === focus.id && !seen.has(node.id)) {
          seen.add(node.id);
          links.push({target: node.id, label: edge.label, direction: 'Arrive from'});
        }
      }
    });
  }
  panel.hidden = !links.length;
  document.body.classList.toggle('has-connections', Boolean(links.length));
  if (!links.length) return;
  panel.append(text('div', 'Follow the context', 'panel-title'),
    text('p', 'Where this connects to the rest of Yoke.', 'panel-summary'));
  links.forEach(edge => {
    const target = byId.get(edge.target);
    const button = text('button', '', 'connection-card');
    button.append(text('small', edge.direction), text('strong', target.title + ' ↗'),
      text('span', edge.label));
    button.onclick = () => choose(target);
    panel.append(button);
  });
}
function drawConnections(visible) {
  wires.replaceChildren();
  const ns = 'http://www.w3.org/2000/svg';
  function svg(tag, attributes) {
    const el = document.createElementNS(ns, tag);
    Object.entries(attributes).forEach(([key, value]) => el.setAttribute(key, value));
    return el;
  }
  const defs = svg('defs', {}), marker = svg('marker', {id: 'arrow', viewBox: '0 0 10 10',
    refX: 8, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse'});
  marker.append(svg('path', {d: 'M 0 0 L 10 5 L 0 10 z', fill: '#658678'}));
  defs.append(marker); wires.append(defs);
  function proxy(id) {
    let node = byId.get(id);
    while (node && !visible.has(node.id)) node = byId.get(node.parent);
    return node;
  }
  const edges = [], unique = new Set();
  byId.forEach(node => {
    for (const edge of node.connections || []) {
      const a = proxy(node.id), b = proxy(edge.target);
      if (!a || !b || a === b || a === focus || b === focus) continue;
      const key = a.id + ':' + b.id;
      if (unique.has(key)) continue;
      unique.add(key); edges.push([a, b]);
    }
  });
  const active = hovered && visible.has(hovered.id) ? hovered : null;
  const connected = new Set(active ? [active.id] : []);
  edges.forEach(([a, b]) => {
    if (active && (a === active || b === active)) { connected.add(a.id); connected.add(b.id); }
  });
  for (const [id, el] of elements) {
    el.classList.toggle('dimmed', Boolean(active && connected.size > 1 && !connected.has(id)
      && !isAncestor(byId.get(id), active) && !isAncestor(active, byId.get(id))));
    el.classList.toggle('related-node', Boolean(active && connected.has(id)));
  }
  edges.forEach(([a, b]) => {
    if (!showConnections && !(active && (a === active || b === active))) return;
    if (active && connected.size > 1 && a !== active && b !== active) return;
    const x = screen(a), y = screen(b);
    const sameRow = Math.abs(x.y - y.y) < 40;
    const ax = x.x + x.w / 2, bx = y.x + y.w / 2;
    let d;
    if (sameRow) {
      const lane = Math.min(x.y, y.y) - 11;
      d = `M${ax},${x.y} L${ax},${lane} L${bx},${lane} L${bx},${y.y}`;
    } else {
      const down = y.y > x.y, ay = down ? x.y + x.h : x.y;
      const by = down ? y.y : y.y + y.h;
      const start = ay + (down ? 11 : -11), end = by + (down ? -11 : 11);
      const lane = x.x + x.w + 11;
      d = `M${ax},${ay} L${ax},${start} L${lane},${start} L${lane},${end} L${bx},${end} L${bx},${by}`;
    }
    wires.append(svg('path', {d, class: 'connection-line', 'marker-end': 'url(#arrow)'}));
  });
}
function isAncestor(parent, node) {
  while (node) { if (parent === node) return true; node = byId.get(node.parent); }
  return false;
}
document.addEventListener('DOMContentLoaded', () => {
  document.querySelector('#trace').onclick = event => {
    showConnections = !showConnections;
    event.currentTarget.setAttribute('aria-pressed', String(showConnections));
    requestRender();
  };
});
