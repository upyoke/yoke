/* The term index is authored separately from the Sources inventory. */
function renderViewNav() {
  const nav = document.querySelector('#view-nav');
  nav.replaceChildren();
  const view = rootOf(focus)?.view || 'sources';
  for (const [label, target, active] of [
    ['Sources', null, view === 'sources'],
    ['Index', byId.get('view:index'), view === 'index'],
    ['Docs map', byId.get('view:docs-map'), view === 'docs-map'],
  ]) {
    const button = text('button', label, active ? 'active' : '');
    button.onclick = () => choose(target);
    nav.append(button);
  }
}
function renderTermIndex(node) {
  const search = text('input', '', 'term-search');
  search.type = 'search'; search.placeholder = 'Find a term';
  search.setAttribute('aria-label', 'Find a term');
  const list = text('div', '', 'term-list');
  function update() {
    const query = search.value.trim().toLocaleLowerCase();
    const terms = node.children.filter(term =>
      (term.title + ' ' + term.summary + ' ' + (term.aliases || []).join(' ')).toLocaleLowerCase().includes(query));
    list.replaceChildren();
    for (const term of terms) {
      const row = text('article', '', 'term-entry');
      const heading = text('h2', '');
      heading.append(nodeLink(term, term.title));
      row.append(heading, text('p', term.summary));
      if (term.aliases?.length) row.append(text('p', 'Also called: ' + term.aliases.join(', '), 'source-size'));
      for (const id of term.related || []) {
        const source = byId.get(id);
        if (source) row.append(nodeLink(source, 'Source: ' + source.title, 'term-source'));
      }
      list.append(row);
    }
    if (!terms.length) list.append(text('p', 'No matching terms.'));
    notice.textContent = `${terms.length} of ${node.children.length} terms`;
  }
  search.oninput = update;
  world.append(search, list); update();
}
