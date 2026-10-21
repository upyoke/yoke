"""The human explorer preserves depth while keeping each choice bounded."""

import re
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / 'docs/teaching/tools'


@pytest.fixture
def explorer(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    import model
    import render_explorer
    from render_pages import Pages

    loaded = model.load()
    pages = Pages(loaded, {}, model.coverage(loaded), {}, lambda _: None)
    views = {}
    render_explorer.build_explorer(views, pages)
    assert not loaded.problems
    return loaded, views, render_explorer


def test_every_surface_and_teaching_has_a_separate_page(explorer):
    model, views, renderer = explorer
    for kind, table in [('surfaces', model.surfaces), ('teachings', model.teaching)]:
        for rid in table:
            assert renderer.location(kind, rid) in views
    assert 'Earlier proposals' in views['explore/sources/hooks.html']
    assert 'global-native' not in views[renderer.ROOT]
    assert views[renderer.ROOT].count('class="card"') == 10


def test_command_tree_exposes_immediate_children_and_model_links(explorer):
    model, views, renderer = explorer
    for concept in model.concepts.values():
        for command in concept.get('commands', []):
            page = views[renderer.command_path(command)]
            assert 'Mapped concepts &amp; source references' in page
    root = views[renderer.command_path('yoke')]
    assert 'Pages' in root
    assert 'yoke qa case run --help' not in root


def test_lists_are_bounded_without_losing_topics(explorer):
    model, views, renderer = explorer
    for cid in model.concepts:
        assert renderer.location('topics', cid) in views
    for path, content in views.items():
        if path.endswith('.html'):
            assert content.count('class="card"') <= 12, path
    topic_pages = [v for k, v in views.items()
                   if re.fullmatch(r'explore/topics(?:-page-\d+)?\.html', k)]
    assert sum(page.count('class="card"') for page in topic_pages) == sum(
        node['parent'] is None for node in model.concepts.values()
    )


def test_missing_navigation_assignment_is_actionable(explorer):
    model, _, renderer = explorer
    from render_pages import Pages

    model.surfaces['new-surface'] = {'title': 'New surface'}
    pages = Pages(model, {}, {}, {}, lambda _: None)
    renderer.build_explorer({}, pages)
    assert model.problems[0].code == 'EXPLORER_SOURCE'
    assert 'new-surface' in model.problems[0].message
