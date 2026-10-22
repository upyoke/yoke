/* Research is attached to sources; it never masquerades as delivered context. */
function viewOf(node) {
  return rootOf(node)?.view || 'sources';
}
function renderViewNav() {
  const nav = document.querySelector('#view-nav');
  nav.replaceChildren();
  for (const [id, title] of [['sources', 'Sources'], ['topics', 'Topics'],
    ['journeys', 'Journeys'], ['research', 'Research']]) {
    const link = text('button', title, viewOf(focus) === id ? 'active' : '');
    link.onclick = () => choose(byId.get('view:' + id) || null);
    nav.append(link);
  }
}
function researchLinks(node, container) {
  const groups = Object.entries(node.research_links || {}).filter(([, links]) => links.length);
  if (!groups.length) return;
  const section = text('section', '', 'research-links');
  section.append(text('h2', 'Connected teaching'));
  section.append(text('p', 'Recorded relationships and source citations; these do not establish live delivery.', 'summary'));
  for (const [label, links] of groups) {
    const disclosure = text('details', '', 'research');
    disclosure.append(text('summary', `${label} · ${links.length}`));
    const list = text('ul', '', 'reference-list');
    for (const edge of links) {
      const target = byId.get(edge.target);
      if (!target) continue;
      const item = text('li', '');
      item.append(nodeLink(target, target.title), text('small', edge.reason));
      list.append(item);
    }
    disclosure.append(list); section.append(disclosure);
  }
  container.append(section);
}
function recordValue(value) {
  if (Array.isArray(value)) {
    const list = text('ul', '');
    value.forEach(item => { const li = text('li', ''); li.append(recordValue(item)); list.append(li); });
    return list;
  }
  if (value && typeof value === 'object') {
    const list = text('dl', '');
    for (const [key, item] of Object.entries(value)) {
      list.append(text('dt', key.replaceAll('_', ' ')));
      const dd = text('dd', ''); dd.append(recordValue(item)); list.append(dd);
    }
    return list;
  }
  return text('p', String(value));
}
async function fillResearch(node, body) {
  if (!records.has(node.record)) records.set(node.record,
    fetch(node.record).then(r => { if (!r.ok) throw Error(r.status); return r.json(); }));
  const record = await records.get(node.record);
  const labels = {current: 'Recorded current state', desired: 'Proposed teaching',
    planned: 'Planned changes', proposed_content: 'Proposed content', text: 'Details',
    note: 'Explanation', need: 'What the reader needs', when: 'When it is needed',
    encounter: 'When it appears', location: 'Where it comes from', audience: 'Who reads it',
    scope: 'Scope', gap: 'What is missing', verification: 'Verification', review: 'Review'};
  for (const [key, label] of Object.entries(labels)) {
    if (!record[key]) continue;
    const row = text('div', '', 'field');
    row.append(text('h3', label), recordValue(record[key])); body.append(row);
  }
  const notes = text('details', '', 'research');
  notes.append(text('summary', 'All record fields and citations'));
  for (const [key, value] of Object.entries(record)) {
    if (key in labels) continue;
    const row = text('div', '', 'field');
    row.append(text('b', key.replaceAll('_', ' ')), recordValue(value)); notes.append(row);
  }
  body.append(notes);
  const source = text('a', 'Open canonical research record ↗');
  source.href = node.record; source.target = '_blank'; source.rel = 'noopener'; body.append(source);
}

async function showBuildInfo() {
  const response = await fetch('build-info.json', {cache: 'no-store'});
  if (!response.ok) return;
  const info = await response.json();
  const box = document.querySelector('#build-info');
  box.append(text('p', `Built ${new Date(info.built_at).toLocaleString()} from ${info.input_files} inspected files.`));
  box.append(text('p', `Checkout: ${info.commit}${info.dirty ? ' + uncommitted changes' : ''}`));
  box.append(text('p', `Input fingerprint: ${info.input_digest}`));
  box.append(text('p', 'Source content and inventories are rebuilt from this checkout. Research retains its recorded state; rebuilding does not reverify evidence.'));
  box.append(text('p', 'Refresh source data: yoke dev run -- python3 docs/teaching/tools/build.py'));
}
