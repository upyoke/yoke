/* Responsive context catalogue: normal document flow and explicit navigation. */
'use strict';
const world = document.querySelector('#world');
const notice = document.querySelector('#notice');
const byId = new Map(), records = new Map();
let roots = [], focus = null;
const navigation = [];
const text = (tag, value, className = '') => {
  const el = document.createElement(tag);
  el.textContent = value;
  el.className = className;
  return el;
};
function choose(node, remember = true) {
  if (remember && focus && focus !== node) navigation.push(focus);
  focus = node;
  if (remember) history.pushState(null, '', node ? '#' + encodeURIComponent(node.id) : location.pathname);
  render();
  window.scrollTo(0, 0);
}
function home() { navigation.length = 0; choose(null); }
window.addEventListener('popstate', () => {
  navigation.length = 0;
  choose(byId.get(decodeURIComponent(location.hash.slice(1))) || null, false);
});
function nodeLink(node, label, className = '') {
  const link = text('a', label, className);
  link.href = '#' + encodeURIComponent(node.id);
  link.onclick = event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); choose(node);
  };
  return link;
}
function makeCard(node) {
  const card = text('article', '', 'node');
  card.dataset.type = node.node_type;
  card.dataset.scope = node.guidance_scope;
  card.append(typeBadge(node));
  const title = text('h2', '');
  title.append(nodeLink(node, node.title));
  card.append(title);
  if (node.summary) card.append(text('p', node.summary, 'summary'));
  appendSizes(card, node);
  card.append(nodeLink(node, node.children.length
    ? `Explore ${node.children.length} ${node.children.length === 1 ? 'entry' : 'entries'} →`
    : 'Read details →', 'card-link'));
  return card;
}
function render() {
  world.replaceChildren();
  updateTrail(); updateSourceList(); updateConnections();
  const heading = text('section', '', 'page-heading');
  if (focus) heading.append(typeBadge(focus));
  heading.append(text('h1', focus ? focus.title : 'What teaches Yoke'));
  heading.append(text('p', focus ? focus.summary : 'Browse the sources, then open a topic to see its contents.', 'summary'));
  if (focus) appendSizes(heading, focus);
  world.append(heading);
  const children = focus ? focus.children : roots;
  if (children.length) {
    const grid = text('div', '', 'card-grid');
    children.forEach(node => grid.append(makeCard(node)));
    world.append(grid);
  }
  if (focus && (focus.body || focus.document || focus.record || focus.url)) {
    const section = document.createElement(children.length ? 'details' : 'section');
    section.className = 'full-content';
    if (children.length) section.append(text('summary', 'Read full content'));
    section.append(text('div', '', 'detail'));
    world.append(section);
    if (children.length) section.ontoggle = () => { if (section.open) fillDetail(focus, section); };
    else fillDetail(focus, section);
  }
  notice.textContent = `${children.length} ${children.length === 1 ? 'entry' : 'entries'}`;
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
    const selected = byId.get(decodeURIComponent(location.hash.slice(1)));
    choose(selected || null, false);
  } catch (error) {
    notice.textContent = 'Map could not load. Serve the checkout over localhost, rebuild the views, then reload.';
    notice.classList.add('error');
  }
})();
