/* Coverage reports explicit draft mappings, not actual content completeness. */
function mapLinks(ids, label, container) {
  const section = text('details', '', 'map-disclosure');
  section.append(text('summary', `${label} · ${ids.length}`));
  section.open = ids.length > 0 && ids.length <= 25 &&
    ['Related index terms', 'Selected commands and command groups', 'Selected teaching sources', 'Continue to detailed sections'].includes(label);
  const list = text('ul', '', 'map-links');
  ids.forEach(id => {
    const node = byId.get(id);
    if (!node) return;
    const li = text('li', ''); li.append(nodeLink(node, node.title)); list.append(li);
  });
  if (!ids.length) list.append(text('li', 'None mapped yet.'));
  section.append(list); container.append(section);
}
function coveragePanel(root, container) {
  const coverage = root.map_coverage;
  const panel = text('section', '', 'map-coverage');
  panel.append(text('h2', 'Coverage and sizing'));
  panel.append(text('p', 'Counts include detailed pages only. Getting started summaries do not count as detailed coverage. A group selection includes its descendants; it marks related material to review, not content to copy.'));
  const table = text('table', '', 'map-table');
  const header = text('tr', '');
  ['Inventory', 'Mapped', 'Unmapped', 'Total'].forEach(label => header.append(text('th', label)));
  table.append(header);
  for (const [key, label] of [['terms', 'Index terms'], ['commands', 'Command leaves'], ['sources', 'Source documents and teaching outputs']]) {
    const stats = coverage[key], row = text('tr', '');
    [label, stats.mapped, stats.unmapped.length, stats.total].forEach(value => row.append(text('td', String(value))));
    table.append(row);
  }
  panel.append(table);
  const filter = text('input', '', 'term-search');
  filter.type = 'search'; filter.placeholder = 'Filter unmapped material';
  filter.setAttribute('aria-label', 'Filter unmapped material');
  const gaps = text('div', '');
  function update() {
    gaps.replaceChildren();
    for (const [key, label] of [['terms', 'Unmapped terms'], ['commands', 'Unmapped commands'], ['sources', 'Unmapped source entries']]) {
      const ids = coverage[key].unmapped.filter(id => byId.get(id)?.title.toLowerCase().includes(filter.value.toLowerCase()));
      mapLinks(ids, label, gaps);
    }
  }
  filter.oninput = update; panel.append(filter, gaps); update();
  mapLinks(coverage.sizing, 'Pages to review for size', panel);
  panel.append(text('p', 'Sizing prompts: more than 15 terms, 40 command leaves or 30 source entries. These are review prompts, not page-length estimates or mandatory splits.', 'summary'));
  mapLinks(coverage.questions, 'Pages with open questions', panel);
  const overlaps = text('details', '', 'map-disclosure');
  overlaps.append(text('summary', `Terms linked to several detailed pages · ${Object.keys(coverage.multiple_term_pages).length}`));
  overlaps.append(text('p', 'Some overlap is useful. Choose a main explanation and cross-link the others when writing content.'));
  for (const [term, pages] of Object.entries(coverage.multiple_term_pages)) {
    const row = text('div', '', 'term-entry');
    row.append(nodeLink(byId.get(term), byId.get(term).title));
    const links = text('p', '');
    pages.forEach(id => links.append(nodeLink(byId.get(id), byId.get(id).title, 'map-chip')));
    row.append(links); overlaps.append(row);
  }
  panel.append(overlaps); container.append(panel);
}
function renderProposedPages(node) {
  if (node?.proposed_pages?.length) mapLinks(node.proposed_pages, 'Proposed documentation pages', world);
}
