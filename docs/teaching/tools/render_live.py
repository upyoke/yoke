"""Compatibility routes for documentation links and registry coverage."""
from render_redirects import redirect

LIVE = '../live/'


def docs_pages(pages, views):
    here = LIVE + 'docs-graph.html'
    views[here] = redirect(here, 'inventory:docs')
    for area in pages.m.docs_graph.get('areas', []):
        here = LIVE + 'docs-graph/' + area['id'] + '.html'
        anchors = {path: 'inventory:doc:' + path for path in pages.docs
                   if pages.area_of(path) == area['id']}
        views[here] = redirect(here, 'inventory:docs:' + area['id'], anchors)


def commands_page(pages, views):
    here = LIVE + 'commands.html'
    views[here] = redirect(here, 'inventory:commands', {
        'unmapped-' + kind: 'inventory:' + kind + ':coverage'
        for kind in ('commands', 'functions', 'skills')})
