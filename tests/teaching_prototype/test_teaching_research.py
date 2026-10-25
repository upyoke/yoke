"""Research survives the unified guide with explicit, reversible source links."""
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


def test_every_canonical_record_has_one_home_and_all_edges_resolve(guide):
    from model import all_records
    from explorer_research import research_id
    loaded, _, nodes, _ = guide
    for kind, key, record in all_records(loaded):
        node = nodes[research_id(kind, key)]
        assert node['record'].endswith(record['file'].removeprefix('docs/teaching/'))
        assert node['record_id'] == key
        assert not node.get('output_size')
    for node in nodes.values():
        assert not node['parent'] or node['parent'] in nodes
        for edges in node.get('research_links', {}).values():
            assert len({edge['target'] for edge in edges}) == len(edges)
            assert all(edge['target'] in nodes and edge['reason'] for edge in edges)


def test_topic_and_surface_connections_are_bidirectional(guide):
    _, _, nodes, _ = guide
    topic = nodes['research:concept:basics/surfaces']
    teaching = nodes['research:teaching:agent-help/01']
    assert any(e['target'] == topic['id'] for e in teaching['research_links']['Topics'])
    assert any(e['target'] == teaching['id'] for e in topic['research_links']['Teaching plans'])
    assert any(e['target'] == 'source:skills' for e in topic['research_links']['Sources'])
    assert topic['coverage'] > 0
    assert any(n.get('coverage') == 0 for n in nodes.values())


def test_proposals_and_history_do_not_change_source_output_totals(guide):
    from render_explorer import map_nodes
    loaded, _, nodes, _ = guide
    for source in map_nodes(loaded):
        assert nodes[source['id']].get('output_size') == source.get('output_size')
    for node in nodes.values():
        if node.get('status') == 'superseded':
            assert node['parent'] == 'research-index:history'
    assert nodes['research:surface:workbench-cues']['parent'] == 'research-index:dashboard'


def test_only_unified_guide_is_generated_and_every_node_is_reachable(guide):
    _, _, nodes, views = guide
    assert list(views) == ['yokepedia.html']
    for node in nodes.values():
        seen = set()
        while node['parent']:
            assert node['id'] not in seen
            seen.add(node['id'])
            node = nodes[node['parent']]


def test_live_inventories_preserve_every_registry_entry_and_document(guide):
    _, pages, nodes, _ = guide
    for kind, values in pages.live.items():
        if kind in ('commands', 'functions', 'skills'):
            for value in values:
                assert 'inventory:' + kind + ':coverage:' + value in nodes
    for path, targets in pages.docs.items():
        node = nodes['inventory:doc:' + path]
        links = node.get('research_links', {}).get('Links to', [])
        assert {e['target'] for e in links} == {
            'inventory:doc:' + target for target in targets if target in pages.docs and target != path}


def test_source_citation_matches_are_exact_and_never_proof():
    from explorer_research import add_research
    from model import Model
    model = Model()
    model.gaps['missing'] = dict(id='missing', title='A gap', status='observed',
                                file='docs/teaching/model/gaps/missing.json', sources=['a.md:12'])
    nodes = [dict(id='doc:a', title='A', parent=None, document='../../../a.md'),
             dict(id='doc:b', title='A', parent=None, document='../../../b.md')]
    add_research(nodes, model)
    by_id = {n['id']: n for n in nodes}
    assert by_id['doc:a']['research_links']['Gaps'][0]['reason'] == 'Cites this source file'
    assert 'research_links' not in by_id['doc:b']
    assert by_id['research:gap:missing']['status_label'].endswith('not live delivery proof')


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


def test_runtime_excerpt_receives_evidence_without_claiming_exact_proof(guide):
    _, _, nodes, _ = guide
    orientation = nodes['hook:global:orientation']
    evidence = orientation['research_links']['Evidence']
    assert any(edge['target'] == 'research:evidence:agent-entry-context/global-orientation'
               and edge['reason'] == 'Cites the containing source file' for edge in evidence)
