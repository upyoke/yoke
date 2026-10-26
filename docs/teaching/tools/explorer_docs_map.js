/* A page specification with source-backed relationships, not generated prose. */
function mapTree(nodes, container, query = '') {
  function matches(node) {
    return (node.title + ' ' + node.summary).toLowerCase().includes(query)
      || node.children.some(matches);
  }
  const list = text('ul', '', 'page-tree');
  for (const node of nodes.filter(matches)) {
    const li = text('li', '');
    li.append(nodeLink(node, node.title));
    const count = node.map_counts;
    li.append(text('small', `${node.page_spec.kind} · ${count.terms} terms · ${count.commands} commands · ${count.sources} sources`));
    li.append(text('p', node.summary));
    if (node.children.length) mapTree(node.children, li, query);
    list.append(li);
  }
  container.append(list);
}
function renderDocsMap(node) {
  if (node.id === 'view:docs-map') {
    world.append(text('p', `${node.page_count} proposed pages, including section landing pages and short Getting started pages. Routes and structure are proposals; the public site is unchanged.`));
    const search = text('input', '', 'term-search');
    search.type = 'search'; search.placeholder = 'Find a proposed page';
    search.setAttribute('aria-label', 'Find a proposed page');
    const tree = text('section', '');
    function update() { tree.replaceChildren(); mapTree(node.children, tree, search.value.toLowerCase()); }
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
    mapTree(node.children, children); world.append(children);
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
