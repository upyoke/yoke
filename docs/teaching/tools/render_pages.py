"""Compatibility routes from the former catalogue to canonical guide records."""
from render_redirects import redirect
from render_live import LIVE as LIVE, commands_page, docs_pages
from explorer_research import research_id


class Pages:
    def __init__(self, model, live, coverage, docs, area_of):
        self.m, self.live, self.cov = model, live, coverage
        self.docs, self.area_of = docs, area_of

    def concept_pages(self, views):
        views['concepts.html'] = redirect('concepts.html', 'view:topics')
        for entry in self.m.concept_files:
            here = f"concepts/{entry['stem']}.html"
            anchors = {key: research_id('concept', key) for key, record in self.m.concepts.items()
                       if record['page'] == entry['stem']}
            views[here] = redirect(here, next(iter(anchors.values()), 'view:topics'), anchors)

    def owned_pages(self, views, kind, table, parts, title):
        owner_kind, part_kind, index = (
            ('surface', 'teaching', 'research-index:surfaces') if kind == 'surfaces'
            else ('scenario', 'lesson', 'view:journeys'))
        views[kind + '.html'] = redirect(kind + '.html', index)
        routes = {}
        for key, record in table.items():
            routes.setdefault(record['page'], {})[key] = research_id(owner_kind, key)
        for key, record in parts.items():
            routes.setdefault(record['page'], {})[key] = research_id(part_kind, key)
        for name, anchors in routes.items():
            here = f'{kind}/{name}.html'
            views[here] = redirect(here, next(iter(anchors.values())), anchors)

    def evidence_pages(self, views):
        views['evidence.html'] = redirect('evidence.html', 'research-index:evidence')
        for group in self.m.evidence_files:
            here = f"evidence/{group['stem']}.html"
            anchors = {f"{group['stem']}/{record['id']}":
                       research_id('evidence', f"{group['stem']}/{record['id']}")
                       for record in group['records']}
            views[here] = redirect(here, 'research-collection:' + group['id'], anchors)

    def record_page(self, views, name, title, table):
        kind = 'gap' if name == 'gaps.html' else 'boundary'
        index = 'research-index:gaps' if kind == 'gap' else 'research-index:boundaries'
        anchors = {key: research_id(kind, key) for key in table}
        views[name] = redirect(name, index, anchors)
        if kind == 'gap':
            for key, target in anchors.items():
                here = f'gaps/{key}.html'
                views[here] = redirect(here, target, {key: target})

    def docs_pages(self, views):
        docs_pages(self, views)

    def commands_page(self, views):
        commands_page(self, views)
