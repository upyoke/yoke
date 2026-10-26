/* Decision records and source build information. */
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
function fillRecord(node, record, body) {
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
  const source = text('a', 'Open decision record ↗');
  source.href = node.record; source.target = '_blank'; source.rel = 'noopener'; body.append(source);
}

function showBuildInfo(info) {
  const box = document.querySelector('#build-info');
  box.append(text('p', `Built ${new Date(info.built_at).toLocaleString()} from ${info.input_files} inspected files.`));
  box.append(text('p', `Checkout: ${info.commit}${info.dirty ? ' + uncommitted changes' : ''}`));
  box.append(text('p', `Input fingerprint: ${info.input_digest}`));
  box.append(text('p', 'Source content and inventories are rebuilt from this checkout. Decision records retain their recorded state; rebuilding does not reverify evidence.'));
  box.append(text('p', 'Refresh source data: yoke dev yokepedia'));
}
