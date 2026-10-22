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
    seen.add(focus.canonical || focus.id);
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

const nodeIcons = {
  group: 'M3 5h7l2 2h9v13H3z',
  'command-group': 'M3 5h7l2 2h9v13H3z M7 11l3 3-3 3m6 0h4',
  command: 'M3 4h18v16H3z M6 9l4 3-4 3m7 1h4',
  file: 'M5 2h9l5 5v15H5z M14 2v6h5M8 12h8M8 16h6',
  page: 'M3 4h18v16H3z M3 9h18M6 6.5h1m2 0h1',
  concept: 'M12 2l10 10-10 10L2 12z M8 12h8',
  section: 'M5 6h14M5 10h14M5 14h10M5 18h7',
  action: 'M4 12h16M14 6l6 6-6 6',
  hook: 'M13 2L5 13h6l-1 9 9-13h-7z',
  reply: 'M3 4h18v13H9l-6 4z M7 8h10M7 12h7',
  screen: 'M2 3h20v14H2z M8 22h8M12 17v5',
  packet: 'M8 3H3v18h5M16 3h5v18h-5M8 8h8M8 12h8M8 16h5',
  rule: 'M12 2l9 4v7c0 5-9 9-9 9S3 18 3 13V6z M8 12l3 3 5-6',
  prompt: 'M4 6h6v7H5v5M14 6h6v7h-5v5',
};
function typeBadge(node) {
  const badge = text('div', '', 'type-badge');
  badge.title = node.type_hint;
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', nodeIcons[node.node_type] || nodeIcons.group);
  icon.append(path); badge.append(icon, text('span', node.type_label));
  const scope = text('span', '', 'scope-badge');
  const scopeIcon = icon.cloneNode(true);
  scopeIcon.querySelector('path').setAttribute('d', node.guidance_scope === 'repository'
    ? 'M5 3v12a4 4 0 004 4h10M5 7h10V3m0 4v5'
    : 'M12 2a10 10 0 100 20 10 10 0 000-20M2 12h20M12 2c-6 6-6 14 0 20 6-6 6-14 0-20');
  scope.append(scopeIcon, text('span', node.scope_label));
  if ((!node.hook_context || node.node_type === 'hook') && node.node_type !== 'section') badge.append(scope);
  if (node.applicability) {
    const applies = text('span', 'Applies to: ' + node.applicability.join(' · '), 'applicability-badge');
    badge.append(applies);
    if (node.delivery_label) badge.append(text('span', node.delivery_label, 'delivery-badge'));
  }
  return badge;
}

function appendSizes(heading, node) {
  if (node.message_estimate) {
    const estimate = text('p', node.message_estimate.label, 'source-size');
    estimate.title = node.message_estimate.assumptions;
    heading.append(estimate);
  }
  if (node.source_size && !node.output_size) {
    const size = node.source_size;
    const badge = text('p', `${size.label} · ${size.lines.toLocaleString()} lines · ${size.bytes.toLocaleString()} B`, 'source-size');
    badge.title = `${size.chars.toLocaleString()} characters · UTF-8 bytes; variable deliveries may differ`;
    heading.append(badge);
  }
}

// A representation carries the real subtree in its current place in the map.
function expandRepresentations() {
  function copy(source, parent, ancestors) {
    if (ancestors.has(source.id)) return null;
    const next = new Set(ancestors).add(source.id);
    const node = {...source, id: parent.id + '::' + source.id, parent: parent.id,
      canonical: source.canonical || source.id, children: []};
    node.children = source.children.map(child => copy(child, node, next)).filter(Boolean);
    byId.set(node.id, node);
    return node;
  }
  [...byId.values()].filter(node => node.represents).forEach(node => {
    const target = byId.get(node.represents);
    if (!target || target === node) return;
    node.canonical = target.id;
    node.children = target.children.map(child => copy(child, node, new Set([target.id]))).filter(Boolean);
    node.connections = target.connections;
  });
}

function updateTrail() {
  const trail = document.querySelector('#trail');
  trail.replaceChildren();
  if (navigation.length) {
    const back = text('button', '← Back to ' + navigation[navigation.length - 1].title);
    back.onclick = () => choose(navigation.pop(), false);
    trail.append(back);
  }
  const all = text('button', 'Whole map');
  all.onclick = home;
  trail.append(all);
  const chain = [];
  for (let n = focus; n; n = byId.get(n.parent)) chain.unshift(n);
  chain.forEach(node => {
    trail.append(text('span', '/'));
    const button = text('button', node.title);
    button.onclick = () => choose(node);
    trail.append(button);
  });
}

function fitPreview(el) {
  const preview = el.querySelector('.preview-children');
  if (!preview) return;
  if (!preview.getClientRects().length) {
    el.querySelector('.count').hidden = false;
    preview.dataset.fit = '';
    return;
  }
  const key = `${el.clientWidth}:${el.clientHeight}:${el.className}`;
  if (preview.dataset.fit === key) return;
  preview.dataset.fit = key;
  const entries = [...preview.children];
  entries.forEach(entry => { entry.hidden = false; });
  const ends = entries.map(entry => entry.offsetTop + entry.offsetHeight);
  const bottom = el.clientHeight - (ends.every(end => end <= el.clientHeight - 22) ? 22 : 58);
  // Measure the wrapped rows before hiding any entries, so a partial row never leaks out.
  const fits = ends.map(end => end <= bottom);
  entries.forEach((entry, i) => { entry.hidden = !fits[i]; });
  const shown = fits.filter(Boolean).length;
  const all = el.querySelector('.count');
  all.hidden = shown === entries.length;
  all.textContent = `Show all ${entries.length} →`;
  all.title = `${shown} of ${entries.length} shown. Open this node to explore every child.`;
}
