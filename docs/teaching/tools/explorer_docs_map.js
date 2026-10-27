function appendMapSubtopics(parent, title, spec, ancestors = []) {
  if (ancestors.includes(title)) return;
  const topic = (spec.topics || []).find(topic => topic.title === title);
  if (!topic || !topic.outline.length) return;
  const list = document.createElement('ul');
  topic.outline.forEach(detail => {
    const row = text('li', detail);
    appendMapSubtopics(row, detail, spec, [...ancestors, title]);
    list.append(row);
  });
  parent.append(list);
}
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
    world.append(text('p', `${node.page_count} public pages · Bold titles are pages; bullets are topics within them. Click a page for its detailed outline, commands, and sources.`, 'map-overview-help'));
    const search = text('input', '', 'term-search');
    search.type = 'search'; search.placeholder = 'Find a page';
    search.setAttribute('aria-label', 'Find a page');
    const tree = text('section', '');
    const topicToggle = text('label', '', 'map-topic-toggle');
    const showTopics = document.createElement('input');
    showTopics.type = 'checkbox'; showTopics.checked = true;
    topicToggle.append(showTopics, document.createTextNode('Show sections and subtopics'));
    function update() { tree.replaceChildren(); compactDocsOutline(node.children, tree, search.value.toLowerCase(), showTopics.checked); }
    showTopics.onchange = update;
    search.oninput = update; world.append(search, topicToggle, tree); update();
    const coverage = text('details', '', 'map-coverage-details');
    coverage.append(text('summary', 'Coverage, gaps, and sizing'));
    coveragePanel(node, coverage); world.append(coverage);
    notice.textContent = 'Public documentation structure';
    return;
  }
  const spec = node.page_spec;
  world.append(text('p', `${spec.kind === 'overview' ? 'Human overview' : 'Detailed topic home'} · Public route: ${spec.route}`, 'summary'));
  world.append(text('p', 'Reader: ' + spec.audience));
  const source = byId.get('doc:' + spec.public_source);
  if (source) world.append(nodeLink(source, 'Read the public page', 'card-link'));
  const outline = text('section', ''); outline.append(text('h2', 'Topics on this page'));
  const points = text('ol', '');
  spec.outline.forEach(point => {
    const item = text('li', point);
    appendMapSubtopics(item, point, spec);
    points.append(item);
  });
  outline.append(points); world.append(outline);
  world.append(text('p', 'Every page starts with a short plain-language explanation. Detailed commands and field contracts follow only where needed; link to agent-delivered guidance instead of copying it.', 'summary'));
  if (node.children.length) {
    const children = text('section', ''); children.append(text('h2', 'Related pages'));
    mapTiles(node.children, children); world.append(children);
  }
  mapLinks(spec.deeper_pages, 'Continue to detailed sections', world);
  mapLinks(spec.terms, 'Related index terms', world);
  mapLinks(spec.commands, 'Selected commands and command groups', world);
  mapLinks(node.expanded_commands, 'Commands included by those groups', world);
  mapLinks(spec.sources, 'Selected teaching sources', world);
  mapLinks(node.expanded_sources, 'Source entries included by those selections', world);
  if (spec.kind === 'overview') world.append(text('p', 'This overview introduces the main topics. Follow the detailed pages for their full mapping.'));
  const questions = text('section', ''); questions.append(text('h2', 'Open decisions'));
  if (spec.open_questions.length) {
    const list = text('ul', ''); spec.open_questions.forEach(q => list.append(text('li', q))); questions.append(list);
  } else questions.append(text('p', 'No open decisions recorded.'));
  world.append(questions);
  notice.textContent = `${node.map_counts.terms} terms · ${node.map_counts.commands} command leaves · ${node.map_counts.sources} source entries`;
}
function compactDocsOutline(nodes, container, query, showTopics) {
  function matches(node) {
    return (node.title + ' ' + node.page_spec.outline.join(' ')).toLowerCase().includes(query)
      || node.children.some(matches);
  }
  function children(nodes, parent) {
    const list = text('ul', '', 'map-outline-children');
    for (const node of nodes.filter(matches)) {
      const row = text('li', ''); row.append(nodeLink(node, node.title));
      topics(node, row);
      if (node.children.length) children(node.children, row);
      list.append(row);
    }
    parent.append(list);
  }
  function topics(node, parent) {
    if (!showTopics) return;
    const list = text('ul', '', 'map-outline-topics');
    list.setAttribute('aria-label', 'Sections in ' + node.title);
    node.page_spec.outline.forEach(title => {
      const row = text('li', title);
      appendMapSubtopics(row, title, node.page_spec);
      list.append(row);
    });
    parent.append(list);
  }
  const grid = text('div', '', 'map-outline-grid');
  for (const node of nodes.filter(matches)) {
    const group = text('section', '', 'map-outline-group');
    const title = text('h2', ''); title.append(nodeLink(node, node.title)); group.append(title);
    topics(node, group);
    children(node.children, group); grid.append(group);
  }
  container.append(grid);
  if (!grid.children.length) container.append(text('p', 'No matching pages or topics.'));
}
