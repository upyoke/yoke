/* The term index is authored separately from the Sources inventory. */
function renderViewNav() {
  const nav = document.querySelector('#view-nav');
  nav.replaceChildren();
  const inIndex = rootOf(focus)?.id === 'view:index';
  for (const [label, target, active] of [
    ['Sources', null, !inIndex], ['Index', byId.get('view:index'), inIndex],
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
      (term.title + ' ' + term.summary).toLocaleLowerCase().includes(query));
    list.replaceChildren();
    for (const term of terms) {
      const row = text('article', '', 'term-entry');
      const heading = text('h2', '');
      heading.append(nodeLink(term, term.title));
      row.append(heading, text('p', term.summary));
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
