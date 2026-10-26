/* A page specification with source-backed relationships, not generated prose. */
function mapTiles(nodes, container, query = '') {
  function matchesPage(node) { return (
    (node.title + ' ' + node.summary + ' ' + node.page_spec.outline.join(' '))
      .toLowerCase().includes(query)); }
  function matchesBranch(node) { return matchesPage(node) || node.children.some(matchesBranch); }
  const matches = nodes.filter(matchesBranch);
  const grid = text('div', '', 'card-grid');
  for (const node of matches) {
    const summary = node.page_spec.outline.join(' · ');
    const card = makeCard({...node, summary,
      type_label: node.page_spec.kind === 'overview' ? 'Human overview' : 'Detailed guide'});
    const count = node.map_counts;
    const facts = text('p', `${count.terms} terms · ${count.commands} commands · ${count.sources} sources`, 'source-size');
    card.insertBefore(facts, card.lastElementChild);
    if (node.children.length) {
      const branch = text('section', '', 'docs-map-branch');
      branch.setAttribute('aria-label', node.title + ' and subpages');
      branch.append(card);
      const children = text('div', '', 'docs-map-children');
      children.append(text('p', 'Subpages of ' + node.title, 'source-size'));
      mapTiles(node.children, children, matchesPage(node) ? '' : query);
      branch.append(children);
      grid.append(branch);
    } else {
      grid.append(card);
    }
  }
  container.append(grid);
  if (!matches.length) container.append(text('p', 'No matching pages.'));
}
function renderDocsMap(node) {
  if (node.id === 'view:docs-map') {
    world.append(text('p', `${node.page_count} proposed pages, including section landing pages and short Getting started pages. Routes and structure are proposals; the public site is unchanged.`));
    const search = text('input', '', 'term-search');
    search.type = 'search'; search.placeholder = 'Find a proposed page';
    search.setAttribute('aria-label', 'Find a proposed page');
    const tree = text('section', '');
    function update() { tree.replaceChildren(); mapTiles(node.children, tree, search.value.toLowerCase()); }
    search.oninput = update; world.append(search, tree); update();
    coveragePanel(node, world);
    notice.textContent = 'Draft structure for review';
    return;
  }
  const spec = node.page_spec;
  world.append(text('p', `${spec.kind === 'overview' ? 'Human overview' : 'Detailed topic home'} · Proposed route: ${spec.route}`, 'summary'));
  world.append(text('p', 'Reader: ' + spec.audience));
  const outline = text('section', ''); outline.append(text('h2', 'What this page should explain'));
  const points = text('ol', ''); spec.outline.forEach(point => points.append(text('li', point)));
  outline.append(points); world.append(outline);
  world.append(text('p', 'Every page starts with a short plain-language explanation. Detailed commands and field contracts follow only where needed; link to agent-delivered guidance instead of copying it.', 'summary'));
  if (node.children.length) {
    const children = text('section', ''); children.append(text('h2', 'Proposed subpages'));
    mapTiles(node.children, children); world.append(children);
  }
  mapLinks(spec.deeper_pages, 'Continue to detailed sections', world);
  mapLinks(spec.terms, 'Related index terms', world);
  mapLinks(spec.commands, 'Selected commands and command groups', world);
  mapLinks(node.expanded_commands, 'Commands included by those groups', world);
  mapLinks(spec.sources, 'Selected teaching sources', world);
  mapLinks(node.expanded_sources, 'Source entries included by those selections', world);
  if (spec.kind === 'overview') world.append(text('p', 'This overview only introduces the topic. Follow its detailed section and subpages for the full mapping.'));
  const questions = text('section', ''); questions.append(text('h2', 'Open decisions'));
  if (spec.open_questions.length) {
    const list = text('ul', ''); spec.open_questions.forEach(q => list.append(text('li', q))); questions.append(list);
  } else questions.append(text('p', 'Review the scope, related material and page size before writing content.'));
  world.append(questions);
  notice.textContent = `${node.map_counts.terms} terms · ${node.map_counts.commands} command leaves · ${node.map_counts.sources} source entries`;
}
