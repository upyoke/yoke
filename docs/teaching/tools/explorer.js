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
const navigation = [];
const palette = ['#487568', '#a37c46', '#657ca5', '#8972a0', '#737c4d'];
const text = (tag, value, className = '') => {
  const el = document.createElement(tag);
  el.textContent = value;
  el.className = className;
  return el;
};
function place(node, x, y, w, h, depth, color, focused = false) {
  Object.assign(node, {x, y, w, h, depth, color});
  const count = node.children.length;
  if (!count) return;
  const cols = Math.min(count, Math.ceil(Math.sqrt(count * w / (h * .7) / 1.6)));
  const rows = Math.ceil(count / cols);
  const gap = focused ? 20 : w * .018, inset = focused ? 22 : w * .04;
  const top = focused ? 210 : h * .25;
  const cw = (w - inset * 2 - gap * (cols - 1)) / cols;
  const ch = (h - top - inset - gap * (rows - 1)) / rows;
  node.children.forEach((child, i) => place(child,
    x + inset + (i % cols) * (cw + gap),
    y + top + Math.floor(i / cols) * (ch + gap), cw, focused && !child.children.length && !child.record && !child.document ? Math.min(ch, 230) : ch,
    depth + 1, color, focused));
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
  // Reflow the selected subtree to the viewport instead of preserving a narrow tile.
  place(node, 24, 62, map.clientWidth - 48, Math.max(240, map.clientHeight - 145),
    node.depth, node.color, true);
  camera = {z: 1, x: 0, y: 0};
}
function choose(node, remember = true) {
  if (!node) return;
  if (remember && focus && focus !== node) navigation.push(focus);
  focus = node;
  node.reading = false;
  updateConnections();
  fit(node);
  document.querySelector('#intro').hidden = true;
  updateTrail();
  updateSourceList();
  requestRender();
}
function home() {
  if (!roots.length) return;
  focus = null;
  navigation.length = 0;
  updateConnections();
  const cols = map.clientWidth > 1150 ? 4 : map.clientWidth > 750 ? 3 : 2;
  const gap = 22, rows = Math.ceil(roots.length / cols), inset = 36;
  const w = (map.clientWidth - inset * 2 - gap * (cols - 1)) / cols;
  const h = Math.max(135, (map.clientHeight - 250 - gap * (rows - 1)) / rows);
  roots.forEach((node, i) => place(node, inset + i % cols * (w + gap),
    165 + Math.floor(i / cols) * (h + gap), w, h, 0, palette[i % palette.length]));
  camera = {z: 1, x: 0, y: 0};
  document.querySelector('#intro').hidden = false;
  updateTrail();
  updateSourceList();
  requestRender();
}
function requestRender() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => { scheduled = false; render(); });
}
function makeNode(node) {
  const el = text('article', '', 'node');
  el.dataset.type = node.node_type;
  el.dataset.scope = node.guidance_scope;
  el.style.setProperty('--accent', node.color);
  el.tabIndex = 0;
  el.setAttribute('aria-label', node.title + '. Zoom into node');
  const heading = text('div', '', 'node-head');
  heading.append(typeBadge(node), text('h2', node.title),
    text('p', node.summary, 'summary'));
  appendSizes(heading, node);
  const context = text('div', node.type_hint, 'type-context');
  context.title = node.type_hint;
  el.append(context);
  el.append(heading);
  if (!node.parent) {
    const preview = text('div', '', 'preview-children');
    node.children.slice(0, 2).forEach(child => preview.append(text('span', child.title)));
    el.append(preview);
  }
  el.onpointerenter = () => { hovered = node; requestRender(); };
  el.onpointerleave = () => { if (hovered === node) hovered = null; requestRender(); };
  el.onfocus = () => { hovered = node; requestRender(); };
  el.onblur = () => { hovered = null; requestRender(); };
  if ((node.record || node.document || node.body) && node.children.length) {
    const read = text('button', 'Read details', 'read-node');
    read.onclick = () => {
      node.reading = !node.reading;
      read.textContent = node.reading ? 'Show branches' : 'Read details';
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
  if (node.body) body.append(text('div', node.body, 'document'));
  if (node.document) {
    try {
      const response = await fetch(node.document);
      if (!response.ok) throw Error(response.status);
      let content = await response.text();
      if (node.document_lines) content = content.split('\n').slice(...node.document_lines).join('\n');
      content = content.replace(/^---[\s\S]*?---\n/, '').replace(/<!--[\s\S]*?-->/g, '');
      const container = node.source_only ? text('details', '', 'research') : body;
      if (node.source_only) {
        container.append(text('summary', 'Source definition'));
        body.append(container);
      }
      container.append(text('div', content, 'document'));
      const source = text('a', 'Open source file ↗');
      source.href = node.document; source.target = '_blank'; source.rel = 'noopener';
      container.append(source);
    } catch (error) {
      body.append(text('p', 'Document could not load. Serve the checkout root and reload.'));
    }
  }
  if (node.url) {
    const link = text('a', 'Open ' + node.title + ' ↗');
    link.href = node.url; link.target = '_blank'; link.rel = 'noopener'; body.append(link);
  }
  for (const edge of node.connections || []) {
    const button = text('button', edge.label + ' →', 'continue-link');
    button.onclick = () => choose(byId.get(edge.target));
    body.append(button);
  }
  if (node.related?.length) {
    body.append(text('b', 'Connected sources'));
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
  if (!roots.length) return;
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
    const child = node.children[0];
    const roomForChildren = child && child.w * camera.z >= 175 && child.h * camera.z >= 105;
    const expanded = focus === node || (focus ? roomForChildren || (!child && s.w > 340 && s.h > 180)
      : camera.z > 1.4 && s.w > 620 && s.h > 370);
    el.classList.toggle('expanded', expanded);
    el.classList.toggle('branches-visible', Boolean(expanded && roomForChildren && !node.reading));
    el.classList.toggle('tiny', s.w < 190 || s.h < 110);
    el.classList.toggle('selected', focus === node);
    el.classList.toggle('leaf', !node.children.length);
    el.classList.toggle('reading', Boolean(node.reading));
    el.classList.toggle('compact', s.h < 185);
    el.style.setProperty('--head-size', `${Math.min(28, Math.max(12, s.w * .058))}px`);
    if (expanded && !node.children.length) fillDetail(node, el);
    if (expanded && roomForChildren && !node.reading) node.children.forEach(visit);
  }
  (focus ? [focus] : roots).forEach(visit);
  for (const [id, el] of elements) if (!visible.has(id)) el.hidden = true;
  drawConnections(visible);
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
window.addEventListener('resize', () => { if (focus) fit(focus); else home(); requestRender(); });
(async () => {
  try {
    const response = await fetch('manifest.json', {cache: 'no-store'});
    if (!response.ok) throw Error('manifest');
    const chunks = await response.json();
    const data = [];
    for (let i = 0; i < chunks.length; i += 24) {
      const batch = await Promise.all(chunks.slice(i, i + 24).map(async name => {
        const r = await fetch(name, {cache: 'no-store'});
        if (!r.ok) throw Error(name); return r.json();
      }));
      data.push(...batch.flat());
    }
    data.forEach(node => byId.set(node.id, {...node, children: []}));
    byId.forEach(node => {
      if (node.parent) byId.get(node.parent).children.push(node);
      else roots.push(node);
    });
    expandRepresentations();
    roots.forEach((node, i) => place(node, (i % 4) * 480,
      Math.floor(i / 4) * 370, 440, 300, 0, palette[i % palette.length]));
    updateSourceList();
    home();
  } catch (error) {
    notice.textContent = 'Map could not load. Serve the checkout over localhost, rebuild the views, then reload.';
    notice.classList.add('error');
  }
})();
