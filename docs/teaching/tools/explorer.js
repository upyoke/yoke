/* One camera over stable nested nodes. Detail is revealed by screen size. */
'use strict';
const map = document.querySelector('#map');
const world = document.querySelector('#world');
const wires = document.querySelector('#wires');
const notice = document.querySelector('#notice');
const byId = new Map();
const elements = new Map();
const records = new Map();
let roots = [], camera = {x: 0, y: 0, z: 1}, focus = null, drag = null;
let scheduled = false;
const palette = ['#28746a', '#b47b35', '#5d77a6', '#7c689a', '#557d46'];
const text = (tag, value, className = '') => {
  const el = document.createElement(tag);
  el.textContent = value;
  el.className = className;
  return el;
};
function place(node, x, y, w, h, depth, color) {
  Object.assign(node, {x, y, w, h, depth, color});
  const count = node.children.length;
  if (!count) return;
  const cols = Math.min(count, Math.ceil(Math.sqrt(count * w / (h * .7) / 1.6)));
  const rows = Math.ceil(count / cols);
  const gap = w * .018, inset = w * .04;
  const top = h * .25;
  const cw = (w - inset * 2 - gap * (cols - 1)) / cols;
  const ch = (h - top - inset - gap * (rows - 1)) / rows;
  node.children.forEach((child, i) => place(child,
    x + inset + (i % cols) * (cw + gap),
    y + top + Math.floor(i / cols) * (ch + gap), cw, ch, depth + 1, color));
}
function screen(node) {
  return {x: node.x * camera.z + camera.x, y: node.y * camera.z + camera.y,
    w: node.w * camera.z, h: node.h * camera.z};
}
function zoom(factor, x = map.clientWidth / 2, y = map.clientHeight / 2) {
  const next = Math.min(1e9, Math.max(.12, camera.z * factor));
  const ratio = next / camera.z;
  camera.x = x - (x - camera.x) * ratio;
  camera.y = y - (y - camera.y) * ratio;
  camera.z = next;
  requestRender();
}
function fit(node) {
  const pad = 90;
  const z = Math.min((map.clientWidth - pad * 2) / node.w,
    (map.clientHeight - pad * 2) / node.h);
  camera = {z, x: (map.clientWidth - node.w * z) / 2 - node.x * z,
    y: (map.clientHeight - node.h * z) / 2 - node.y * z + 20};
}
function choose(node) {
  focus = node;
  fit(node);
  document.querySelector('#intro').hidden = true;
  updateTrail();
  updateConnections();
  requestRender();
}
function home() {
  focus = null;
  const z = Math.min((map.clientWidth - 100) / 1880,
    Math.max(200, map.clientHeight - 250) / (Math.ceil(roots.length / 4) * 370 - 70));
  camera = {z, x: (map.clientWidth - 1880 * z) / 2, y: 175};
  document.querySelector('#intro').hidden = false;
  updateTrail();
  updateConnections();
  requestRender();
}
function updateTrail() {
  const trail = document.querySelector('#trail');
  trail.replaceChildren();
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
function updateConnections() {
  const panel = document.querySelector('#connections');
  panel.replaceChildren();
  panel.hidden = !focus;
  if (!focus) return;
  const links = [];
  // Ancestor connections also apply while reading a child instruction.
  for (let node = focus; node; node = byId.get(node.parent)) {
    for (const edge of node.connections || []) links.push({...edge, from: node});
  }
  byId.forEach(node => {
    for (const edge of node.connections || []) {
      if (edge.target === focus.id) links.push({target: node.id,
        label: 'From ' + node.title + ' · ' + edge.label, from: node});
    }
  });
  panel.hidden = links.length === 0;
  panel.append(text('b', 'Connected steps and sources'));
  links.forEach(edge => {
    const target = byId.get(edge.target);
    const button = text('button', edge.label + ' ↗');
    button.title = target.title;
    button.onclick = () => choose(target);
    panel.append(button);
  });
}
function requestRender() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => { scheduled = false; render(); });
}
function makeNode(node) {
  const el = text('article', '', 'node');
  el.style.setProperty('--accent', node.color);
  el.tabIndex = 0;
  el.setAttribute('aria-label', node.title + '. Zoom into node');
  const heading = text('div', '', 'node-head');
  const labels = {'observed': 'Source reviewed', 'draft-copy': 'Draft wording',
    'candidate': 'Proposed', 'approved': 'Agreed', 'deferred': 'Planned for later',
    'verified-live': 'Checked in use'};
  heading.append(text('span', labels[node.status] || (node.depth ? 'Branch' : 'Context source'), 'kind'),
    text('h2', node.title), text('p', node.summary, 'summary'));
  el.append(heading);
  if ((node.record || node.document) && node.children.length) {
    const read = text('button', 'Read this node', 'read-node');
    read.onclick = () => {
      node.reading = !node.reading;
      read.textContent = node.reading ? 'Show branches' : 'Read this node';
      fillDetail(node, el);
      requestRender();
    };
    el.append(read);
  }
  if (node.children.length) el.append(text('span',
    `${node.children.length} ${node.children.length === 1 ? 'branch' : 'branches'} ↗`, 'count'));
  const detail = text('div', '', 'detail');
  el.append(detail);
  el.onclick = e => { if (!e.target.closest('a,button,.detail')) choose(node); };
  el.onkeydown = e => {
    if (e.target === el && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault(); choose(node);
    }
  };
  world.append(el);
  elements.set(node.id, el);
  return el;
}
async function fillDetail(node, el) {
  if (el.dataset.loaded) return;
  el.dataset.loaded = 'yes';
  const body = el.querySelector('.detail');
  if (node.record) {
    try {
      if (!records.has(node.record)) records.set(node.record,
        fetch(node.record).then(r => { if (!r.ok) throw Error(r.status); return r.json(); }));
      const record = await records.get(node.record);
      const labels = {current: 'What is there now', desired: 'What is intended',
        note: 'Explanation', need: 'What the reader needs', when: 'When it is needed',
        encounter: 'When it appears', location: 'Where it comes from',
        audience: 'Who reads it', scope: 'Where it applies'};
      for (const [key, label] of Object.entries(labels)) {
        if (!record[key]) continue;
        const row = text('div', '', 'field');
        row.append(text('b', label), text('p', String(record[key])));
        body.append(row);
      }
      const research = text('details', '', 'research');
      research.append(text('summary', 'Research notes and source references'));
      for (const [key, value] of Object.entries(record)) {
        if (['id', 'title', 'page', 'position', 'status', 'form', 'topics'].includes(key)
            || key in labels) continue;
        const row = text('div', '', 'field');
        row.append(text('b', key.replaceAll('_', ' ')),
          text('p', Array.isArray(value) ? value.join(' · ') : String(value)));
        research.append(row);
      }
      body.append(research);
      const link = text('a', 'Original research record ↗');
      link.href = node.record; link.target = '_blank'; link.rel = 'noopener';
      body.append(link);
    } catch (error) {
      body.append(text('p', 'Record could not load. Rebuild the views and reload this map.'));
      el.dataset.loaded = '';
    }
  }
  if (node.document) {
    try {
      const response = await fetch(node.document);
      if (!response.ok) throw Error(response.status);
      const content = (await response.text()).replace(/^---[\s\S]*?---\n/, '');
      body.append(text('div', content, 'document'));
    } catch (error) {
      body.append(text('p', 'Document could not load. Serve the checkout root and reload.'));
    }
  }
  if (node.url) {
    const link = text('a', 'Open ' + node.title + ' ↗');
    link.href = node.url; link.target = '_blank'; link.rel = 'noopener'; body.append(link);
  }
  if (node.related?.length) {
    body.append(text('b', 'Related teaching'));
    node.related.forEach(id => {
      const target = byId.get(id);
      if (!target) return;
      const button = text('button', target.title);
      button.onclick = () => choose(target);
      body.append(button);
    });
  }
}
function render() {
  const visible = new Set();
  function visit(node) {
    const s = screen(node);
    if (s.x + s.w < 0 || s.y + s.h < 0 || s.x > map.clientWidth || s.y > map.clientHeight) return;
    if (s.w < 20 || s.h < 12) return;
    visible.add(node.id);
    const el = elements.get(node.id) || makeNode(node);
    el.hidden = false;
    Object.assign(el.style, {left: `${s.x}px`, top: `${s.y}px`,
      width: `${s.w}px`, height: `${s.h}px`, zIndex: node.depth + 1});
    const expanded = focus === node || (s.w > 620 && s.h > 370);
    el.classList.toggle('expanded', expanded);
    el.classList.toggle('tiny', s.w < 190 || s.h < 110);
    el.classList.toggle('selected', focus === node);
    el.classList.toggle('leaf', !node.children.length);
    el.classList.toggle('reading', Boolean(node.reading));
    el.style.setProperty('--head-size', `${Math.min(28, Math.max(12, s.w * .058))}px`);
    if (expanded && !node.children.length) fillDetail(node, el);
    if (expanded && !node.reading) node.children.forEach(visit);
  }
  roots.forEach(visit);
  for (const [id, el] of elements) if (!visible.has(id)) el.hidden = true;
  wires.replaceChildren();
  document.querySelector('#scale').textContent = `${Math.round(camera.z * 100)}%`;
  notice.textContent = focus ? `${focus.title} · ${focus.children.length} branches` : `${roots.length} teaching sources · zoom to reveal their contents`;
}
map.addEventListener('wheel', e => {
  if (e.target.closest('.detail') && !e.ctrlKey && !e.metaKey) return;
  e.preventDefault();
  const rect = map.getBoundingClientRect();
  zoom(Math.exp(-e.deltaY * .002), e.clientX - rect.left, e.clientY - rect.top);
}, {passive: false});
map.addEventListener('pointerdown', e => {
  if (e.target.closest('button,a,.detail') || e.button !== 0) return;
  drag = {x: e.clientX, y: e.clientY, cx: camera.x, cy: camera.y, moved: false};
});
window.addEventListener('pointermove', e => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
  if (drag.moved) { camera.x = drag.cx + dx; camera.y = drag.cy + dy; requestRender(); }
});
window.addEventListener('pointerup', () => {
  if (drag?.moved) map.addEventListener('click', e => e.stopPropagation(), {capture: true, once: true});
  drag = null;
});
map.addEventListener('keydown', e => {
  if (e.key === 'Escape') { e.preventDefault(); up(); }
});
function up() { const parent = byId.get(focus?.parent); if (parent) choose(parent); else home(); }
document.querySelector('#home').onclick = home;
document.querySelector('#up').onclick = up;
document.querySelector('#in').onclick = () => zoom(1.5);
document.querySelector('#out').onclick = () => zoom(1 / 1.5);
window.addEventListener('resize', requestRender);
(async () => {
  try {
    const response = await fetch('manifest.json');
    if (!response.ok) throw Error('manifest');
    const chunks = await response.json();
    const data = (await Promise.all(chunks.map(async name => {
      const r = await fetch(name); if (!r.ok) throw Error(name); return r.json();
    }))).flat();
    data.forEach(node => byId.set(node.id, {...node, children: []}));
    byId.forEach(node => {
      if (node.parent) byId.get(node.parent).children.push(node);
      else roots.push(node);
    });
    roots.forEach((node, i) => place(node, (i % 4) * 480,
      Math.floor(i / 4) * 370, 440, 300, 0, palette[i % palette.length]));
    home();
  } catch (error) {
    notice.textContent = 'Map could not load. Serve the checkout over localhost, rebuild the views, then reload.';
    notice.classList.add('error');
  }
})();
