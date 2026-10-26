/* Responsive context catalogue: normal document flow and explicit navigation. */
'use strict';
const world = document.querySelector('#world');
const notice = document.querySelector('#notice');
const data = JSON.parse(document.querySelector('#yokepedia-data').textContent);
const byId = new Map();
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
  if (node.status_label) card.append(text('p', node.status_label, 'research-status'));
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
  if (focus) {
    appendSizes(heading, focus);
    if (focus.status_label) heading.append(text('p', focus.status_label, 'research-status'));
    if (focus.coverage !== undefined) heading.append(text('p',
      `${focus.coverage} direct teaching mappings. A mapping does not prove delivery.`, 'summary'));
  }
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
const MISSING = ' is missing from this build. Rebuild Yokepedia: yoke dev yokepedia';
function fillDetail(node, el) {
  if (el.dataset.loaded) return;
  el.dataset.loaded = 'yes';
  const body = el.querySelector('.detail');
  if (node.record) {
    if (node.record in data.records) fillRecord(node, data.records[node.record], body);
    else body.append(text('p', 'Decision record' + MISSING, 'error'));
  }
  if (node.body) body.append(text('div', node.body, 'document'));
  if (node.document) {
    let content = data.documents[node.document];
    if (content === undefined) body.append(text('p', 'Source document' + MISSING, 'error'));
    else {
      if (node.document_lines) content = content.split('\n').slice(...node.document_lines).join('\n');
      content = content.replace(/^---[\s\S]*?---\n/, '').replace(/<!-{2}[\s\S]*?-{2}>/g, '');
      const container = node.source_only ? text('details', '', 'research') : body;
      if (node.source_only) {
        container.append(text('summary', 'Source definition'));
        body.append(container);
      }
      container.append(text('div', content, 'document'));
      const source = text('a', 'Open source file ↗');
      source.href = node.document; source.target = '_blank'; source.rel = 'noopener';
      container.append(source);
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
try {
  data.nodes.forEach(node => byId.set(node.id, {...node, children: []}));
  byId.forEach(node => {
    if (node.parent) byId.get(node.parent).children.push(node);
    else roots.push(node);
  });
  expandRepresentations();
  showBuildInfo(data.build);
  choose(byId.get(decodeURIComponent(location.hash.slice(1))) || null, false);
} catch (error) {
  notice.textContent = 'Yokepedia could not start: ' + error.message + '. Rebuild it with yoke dev yokepedia, then reload.';
  notice.classList.add('error');
}
