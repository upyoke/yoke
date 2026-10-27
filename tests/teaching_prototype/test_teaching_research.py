"""Sources, curated terms, and public-page maps replace the retired research views."""
from pathlib import Path

import pytest

from tests.teaching_prototype.yokepedia_page import page_data, page_nodes

TOOLS = Path(__file__).resolve().parents[2] / 'docs/teaching/tools'


@pytest.fixture(scope='module')
def guide():
    import sys
    sys.path.insert(0, str(TOOLS))
    import model
    import inventory
    from guide_data import GuideData
    from render_explorer import build_explorer
    loaded = model.load()
    live = inventory.live_registries()
    docs = inventory.documents(inventory.tracked_files())
    pages = GuideData(loaded, live, docs,
                  lambda path: inventory.area_of(path, loaded.docs_graph))
    views = {}
    build_explorer(views, pages)
    assert not loaded.problems
    nodes = page_nodes(views['yokepedia.html'])
    yield loaded, pages, nodes, views
    sys.path.remove(str(TOOLS))


def test_source_nodes_keep_their_output_totals(guide):
    from render_explorer import map_nodes
    loaded, _, nodes, _ = guide
    for source in map_nodes(loaded):
        assert nodes[source['id']].get('output_size') == source.get('output_size')


def test_retired_research_views_are_absent_and_all_nodes_are_reachable(guide):
    _, _, nodes, views = guide
    assert list(views) == ['yokepedia.html']
    assert not any(key.startswith(('research:', 'research-index:', 'inventory:')) for key in nodes)
    assert {key for key in nodes if key.startswith('view:')} == {
        'view:index', 'view:docs-map', 'view:getting-started'}
    assert 'source:packs' in nodes and 'source:decisions' in nodes
    for node in nodes.values():
        seen = set()
        while node['parent']:
            assert node['id'] not in seen
            seen.add(node['id'])
            node = nodes[node['parent']]


def test_curated_terms_and_aliases_have_sources(guide):
    import json
    _, _, nodes, _ = guide
    for path in (TOOLS.parent / 'model/terms').glob('*.json'):
        record = json.loads(path.read_text())
        term = nodes['term:' + record['id']]
        assert term['title'] == record['term']
        assert term['aliases'] == record.get('aliases', [])
        assert term['parent'] == 'view:index'
        assert {nodes[key]['document'].removeprefix('../../../') for key in term['related']} == set(record['sources'])


def test_map_reads_public_titles_and_topics(guide):
    _, _, nodes, views = guide
    repo = TOOLS.parents[2]
    for node in nodes.values():
        if not node['id'].startswith('page:'):
            continue
        spec = node['page_spec']
        source = (repo / spec['public_source']).read_text()
        assert '# ' + node['title'] in source
        assert all('## ' + heading in source for heading in spec['outline'])
        assert all(key in nodes for key in spec['terms'] + spec['commands'] + spec['sources'])
    intro = page_data(views['yokepedia.html'])['public_intro']
    assert 'install upyoke.com' in intro
    assert 'Getting started' in intro


def test_build_records_source_snapshot_not_delivery_proof(guide):
    _, _, _, views = guide
    info = page_data(views['yokepedia.html'])['build']
    assert len(info['commit']) == 40
    assert len(info['input_digest']) == 64
    assert info['input_files'] > 100
    assert info['built_at']
    assert 'rebuilding does not reverify evidence' in views['yokepedia.html']


def test_source_snapshot_changes_when_source_changes(monkeypatch, tmp_path):
    import explorer_inventory
    import model
    from types import SimpleNamespace
    root = tmp_path / 'repo'
    root.mkdir()
    source = root / 'guide.md'
    source.write_text('First source version')
    monkeypatch.setattr(explorer_inventory, '__file__', str(root / 'docs/teaching/tools/explorer_inventory.py'))
    monkeypatch.setattr(model, 'model_files', lambda: [])
    import subprocess
    monkeypatch.setattr(subprocess, 'check_output', lambda args, **kwargs:
                        'a' * 40 if 'rev-parse' in args else '')
    pages = SimpleNamespace(docs={'guide.md': []}, m=model.Model(), live={})
    first = explorer_inventory.source_snapshot([], pages)
    source.write_text('Updated source, not a copied inventory')
    second = explorer_inventory.source_snapshot([], pages)
    assert first['input_digest'] != second['input_digest']
    assert first['commit'] == second['commit']
