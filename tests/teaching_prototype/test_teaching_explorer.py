"""The spatial view preserves canonical context nodes and relationship chains."""

import json
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


def test_every_surface_teaching_and_concept_is_a_node(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    from explorer_sources import EXCLUDED_SURFACES
    for kind, table in [('surface', model.surfaces), ('teaching', model.teaching),
                        ('topic', model.concepts)]:
        for rid, row in table.items():
            if kind == 'surface' and rid in EXCLUDED_SURFACES:
                assert f'{kind}:{rid}' not in nodes
                continue
            if kind == 'teaching' and (row['owner'] in EXCLUDED_SURFACES
                                        or row['status'] == 'superseded'):
                assert f'{kind}:{rid}' not in nodes
                continue
            assert f'{kind}:{rid}' in nodes
    for node in nodes.values():
        assert not node['parent'] or node['parent'] in nodes
        assert all(target in nodes for target in node.get('related', []))
    assert 'surface:global-native' not in nodes
    assert 'surface:workbench-cues' not in nodes


def test_commands_have_a_hierarchy_and_related_concepts(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    assert nodes['command:yoke']['parent'] == 'source:help'
    for cid, concept in model.concepts.items():
        for command in concept.get('commands', []):
            assert f'topic:{cid}' in nodes['command:' + command]['related']


def test_single_page_and_complete_bounded_data_chunks(explorer):
    model, views, renderer = explorer
    assert [key for key in views if key.endswith('.html')] == [renderer.ROOT]
    manifest = json.loads(views['explore/manifest.json'])
    nodes = [node for name in manifest for node in json.loads(views['explore/' + name])]
    assert len(nodes) == len(renderer.map_nodes(model))
    assert len({node['id'] for node in nodes}) == len(nodes)
    assert all(len(json.loads(views['explore/' + name])) <= 12 for name in manifest)
    for node in nodes:
        for key in ('record', 'document'):
            if node.get(key):
                target = TOOLS.parent / 'views/explore' / node[key]
                assert target.resolve().is_file()


def test_missing_navigation_assignment_is_actionable(explorer):
    model, _, renderer = explorer
    model.surfaces['new-surface'] = {'title': 'New surface'}
    renderer.map_nodes(model)
    assert model.problems[0].code == 'EXPLORER_SOURCE'
    assert 'new-surface' in model.problems[0].message


def test_agreed_sources_and_shared_documentation(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    roots = {node['id'] for node in nodes.values() if node['parent'] is None}
    assert roots == {'source:' + name for name in (
        'homepage', 'docs', 'setup', 'global-hooks', 'project-hooks', 'rules',
        'skills', 'roles', 'help', 'feedback', 'packets', 'instructions', 'project')}
    assert nodes['branch:web-docs']['related'] == nodes['branch:installed-docs']['related']
    assert nodes['topics']['parent'] == 'branch:doc-content'
    assert nodes['role:engineer']['parent'] == 'source:roles'
    assert nodes['skill:dash']['parent'] == 'branch:project-skills'
    assert nodes['skill:yoke-global']['parent'] == 'source:skills'
    assert nodes['surface:resume-context']['parent'] == 'branch:skill-guidance'
