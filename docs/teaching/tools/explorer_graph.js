/* Navigation and relationship tracing share the map's node model. */
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
  roots.filter(node => !node.view).forEach(node => {
    const button = text('button', '', rootOf(focus) === node ? 'active' : '');
    const dot = text('span', '', 'source-dot');
    dot.style.background = '#688b7b';
    button.append(dot, text('span', node.title));
    button.onclick = () => choose(node);
    list.append(button);
  });
}
function updateConnections() {
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
  if (node.research) return badge;
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
    back.onclick = () => history.back();
    trail.append(back);
  }
  const all = text('button', 'Guide');
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
