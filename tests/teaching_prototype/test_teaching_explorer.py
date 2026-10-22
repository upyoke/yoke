"""The responsive guide preserves canonical context nodes and relationship chains."""

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


def test_map_contains_sources_instead_of_research_proposals(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    assert not any(key.startswith(('surface:', 'teaching:', 'topic:')) for key in nodes)
    for node in nodes.values():
        assert not node['parent'] or node['parent'] in nodes
        assert all(target in nodes for target in node.get('related', []))
    assert 'surface:global-native' not in nodes
    assert 'surface:workbench-cues' not in nodes


def test_public_docs_match_the_actual_files_and_category_titles(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    repo = TOOLS.parents[2]
    for path in (repo / 'docs/public').rglob('*.md'):
        key = 'doc:' + path.relative_to(repo).as_posix()
        assert key in nodes
        assert nodes[key]['document'].endswith(path.relative_to(repo).as_posix())
    assert nodes['docs-category:start']['title'] == 'Get started'
    assert nodes['doc:docs/public/start/install.md']['parent'] == 'docs-category:start'
    assert nodes['doc:docs/public/index.md']['parent'] == 'branch:doc-content'
    assert 'overview & contents' in nodes['doc:docs/public/index.md']['title']
    assert 'doc:docs/public/start/index.md' in nodes['doc:docs/public/index.md']['related']


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
    assert {n['id'] for n in nodes.values() if n['parent'] == 'source:docs'} == {
        'branch:web-docs', 'branch:installed-docs', 'branch:doc-content'}
    assert {'target': 'doc:docs/public/index.md', 'label': 'Displays on entry'} in nodes['branch:web-docs']['connections']
    assert nodes['docs-category:start']['parent'] == 'branch:doc-content'
    assert 'topics' not in nodes
    assert nodes['role:engineer']['parent'] == 'source:roles:build'
    assert nodes['skill:dash']['parent'] == 'branch:project-skills:implement-and-deliver'
    assert nodes['skill:yoke-global']['parent'] == 'source:skills'
    assert 'branch:skill-guidance' not in nodes


def test_nested_groups_and_install_connections(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    assert {n['id'] for n in nodes.values() if n['parent'] == 'source:homepage'} == {
        'branch:ask-agent', 'branch:install-command'}
    assert {e['target'] for e in nodes['branch:install-command']['connections']} == {
        'branch:agent-setup', 'branch:terminal-setup'}
    for node in nodes.values():
        assert all(edge['target'] in nodes for edge in node.get('connections', []))
        seen = set()
        while node['parent']:
            assert node['id'] not in seen
            seen.add(node['id'])
            node = nodes[node['parent']]
    assert any(n['title'] == 'Where should this Yoke universe live?' for n in nodes.values())
    assert nodes['skill:implement/implementing']['parent'] == 'skill:implement'


def test_command_map_includes_registered_operations(explorer):
    model, views, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    for command in renderer.registered_commands():
        assert 'command:' + command in nodes
    assert {n['id'] for n in nodes.values() if n['parent'] == 'source:help'} == {
        'command:yoke', 'branch:command-groups'}
    assert nodes['command:yoke actors']['parent'] == 'branch:command-groups'
    assert nodes['help-output:yoke actors']['parent'] == 'command:yoke actors'
    assert 'Usage: yoke actors' in nodes['help-output:yoke actors']['body']
    assert nodes['command:yoke']['output_size']['estimated'] is False
    assert 'explore/explorer_graph.js' in views


def test_node_types_distinguish_forms_and_summaries(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    assert all(node['node_type'] and node['type_label'] and node['type_hint'] for node in nodes.values())
    assert nodes['command:yoke']['type_label'] == 'Main help'
    assert nodes['command:yoke actors']['type_label'] == 'Command group'
    assert nodes['command:yoke actors role set']['type_label'] == 'Command'
    assert nodes['command:yoke agents render']['type_label'] == 'Command + group'
    assert nodes['skill:dash']['type_label'] == 'Skill file'
    assert nodes['role:engineer']['type_label'] == 'Agent-role file'
    assert nodes['branch:ask-agent']['type_label'] == 'Human request'
    assert nodes['source:global-hooks']['node_type'] == 'hook'
    assert nodes['hook:global:orientation']['type_label'] == 'Startup message'
    assert nodes['doc:docs/public/start/install.md']['type_label'] == 'Document'
    assert nodes['packet:main_agent:core']['type_label'] == 'Packet topic'
    assert nodes['instruction:shipped']['type_label'] == 'Instruction text'


def test_setup_pairs_and_source_excerpts_are_real(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    prompts = [n for n in nodes.values() if n['id'].startswith('prompt:') and n.get('related')]
    assert prompts
    for prompt in prompts:
        peer = nodes[prompt['related'][0]]
        assert peer['title'] == prompt['title']
        assert peer['document_lines'] == prompt['document_lines']
    for node in nodes.values():
        if node.get('document_lines'):
            start, end = node['document_lines']
            path = TOOLS.parent / 'views/explore' / node['document']
            assert 0 <= start < end <= len(path.read_text().splitlines())
    assert any(n['type_label'] == 'Answer choice' for n in nodes.values())
    assert any(n['type_label'] == 'Reply field' for n in nodes.values())
    assert nodes['hook-event:PreToolUse']['parent'] == 'source:project-hooks'
    assert nodes['hook-event:global:PreToolUse']['parent'] == 'source:global-hooks'
    assert 'shared-hook-events' not in nodes
    global_modules = {n['hook_module'] for n in nodes.values() if n.get('hook_mode') == 'global'}
    assert 'yoke_core.domain.lint_local_privacy' in global_modules
    assert 'yoke_core.domain.lint_main_commit' not in global_modules
    assert nodes['hook:global:orientation']['node_type'] == 'reply'
    assert nodes['hook:global:orientation:identity']['node_type'] == 'section'


def test_rules_combine_shared_topics_and_only_local_additions(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    topics = [n for n in nodes.values() if n['parent'] == 'source:rules']
    assert topics and all(n['id'].startswith('rules-topic:') for n in topics)
    assert len([n for n in topics if n['title'] == 'Standing authority']) == 1
    assert {n['title'] for n in topics if n['guidance_scope'] == 'repository'} == {
        'Control-Plane Authority — Hard Rule (this installation)',
        'Yoke Repo Internals', 'Source-Dev Doctrine'}
    assert any(n['title'] == 'Rule loading and field notes' and
               n['guidance_scope'] == 'shared' for n in topics)
    local = (TOOLS.parents[2] / 'AGENTS.md').read_text().splitlines()
    end = local.index('<!-- END YOKE MANAGED BLOCK -->')
    for node in topics:
        if node['guidance_scope'] == 'repository':
            assert node['document_lines'][0] > end
    assert nodes['source:rules']['guidance_scope'] == 'mixed'
    assert nodes['doc:docs/source-dev-doctrine.md']['guidance_scope'] == 'repository'
    assert nodes['doc:docs/public/start/install.md']['guidance_scope'] == 'shared'
    assert nodes['skill:dash']['guidance_scope'] == 'shared'
    assert all(n['scope_label'] for n in nodes.values())


def test_source_sizes_measure_exact_utf8_excerpts(explorer, tmp_path, monkeypatch):
    import explorer_documents
    from explorer_types import describe_sizes

    monkeypatch.setattr(explorer_documents, 'REPO', tmp_path)
    raw = 'Heading\r\nCafé 🌍\r\nEnd'.encode('utf-8')
    (tmp_path / 'sample.md').write_bytes(raw)
    nodes = [dict(document='../../../../sample.md'),
             dict(document='../../../../sample.md', document_lines=[1, 2]),
             dict(title='A conceptual group')]
    describe_sizes(nodes)
    assert nodes[0]['source_size']['bytes'] == len(raw)
    assert nodes[0]['source_size']['lines'] == 3
    assert nodes[1]['source_size'] == dict(bytes=len('Café 🌍\r\n'.encode()),
                                         chars=len('Café 🌍\r\n'), lines=1,
                                         label='Context text')
    assert 'source_size' not in nodes[2]
    code = [dict(document='../../../../sample.md', source_only=True)]
    describe_sizes(code)
    assert 'source_size' not in code[0]


def test_delivered_messages_have_topics_without_code_sizes(explorer):
    model, _, renderer = explorer
    nodes = renderer.map_nodes(model)
    for node in nodes:
        if node.get('source_only'):
            assert 'source_size' not in node
        if node.get('hook_module') == 'yoke_core.hooks.session_message_delivery':
            children = [n for n in nodes if n['parent'] == node['id']]
            assert {n['title'] for n in children} >= {'Sender', 'Message body', 'Acknowledge'}
    assert any(n['id'].startswith('doc:docs/public/') and ':topic:' in n['id'] for n in nodes)


def test_output_totals_preserve_known_parts_and_variable_remainder(explorer):
    model, _, renderer = explorer
    nodes = renderer.map_nodes(model)
    for node in nodes:
        size = node['output_size']
        assert 0 <= size['bytes'][0] <= size['bytes'][1]
        assert 0 <= size['lines'][0] <= size['lines'][1]
        assert node['message_estimate']['label']
    incoming = next(n for n in nodes if n.get('hook_module') == 'yoke_core.hooks.session_message_delivery')
    parts = [n for n in nodes if n['parent'] == incoming['id']]
    assert incoming['output_size']['variable']
    for field in ('bytes', 'lines'):
        assert incoming['output_size'][field] == [sum(n['output_size'][field][i] for n in parts) for i in (0, 1)]
    body = next(n for n in parts if n['title'] == 'Message body')
    assert body['output_size']['variable']
    assert next(n for n in parts if n['title'] == 'Acknowledge')['output_size']['bytes'][0] > 0
    document = next(n for n in nodes if n.get('source_size') and any(c['parent'] == n['id'] for c in nodes))
    assert document['output_size']['bytes'] == [document['source_size']['bytes']] * 2


def test_encounter_order_and_hook_lifecycle(explorer):
    model, _, renderer = explorer
    nodes = renderer.map_nodes(model)
    expected = ['SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PermissionRequest',
                'PostToolUse', 'PostToolUseFailure', 'Stop', 'SessionEnd']
    for scope in ('global', 'project'):
        children = [n for n in nodes if n['parent'] == 'source:' + scope + '-hooks']
        assert [n['id'].rsplit(':', 1)[-1] for n in children] == expected
    assert next(n for n in nodes if n['parent'] == 'source:setup')['id'] == 'installer:script'
    assert next(n for n in nodes if n['parent'] == 'source:skills')['id'] == 'skill:yoke-global'
    assert next(n for n in nodes if n['parent'] == 'source:roles:plan-and-design')['id'] == 'role:product-manager'
    docs = [n['id'] for n in nodes if n['parent'] == 'branch:doc-content']
    assert docs[:2] == ['doc:docs/public/index.md', 'docs-category:start']


def test_install_modes_represent_real_setup_subtrees(explorer):
    model, _, renderer = explorer
    nodes = {node['id']: node for node in renderer.map_nodes(model)}
    for alias, target in (('branch:install-human', 'branch:terminal-setup'),
                          ('branch:install-agent', 'branch:agent-setup')):
        assert nodes[alias]['represents'] == target
        assert any(node['parent'] == target for node in nodes.values())
        assert nodes[alias]['message_estimate'] == nodes[target]['message_estimate']
        assert not nodes[alias]['connections']


def test_guide_uses_document_grid_without_canvas_controls(explorer):
    _, views, _ = explorer
    html = views['explore/index.html']
    assert '<main id="main">' in html
    assert 'id="wires"' not in html
    assert 'id="tools"' not in html
    css = views['explore/explorer.css']
    assert 'grid-template-columns: repeat(auto-fit' in css
    script = views['explore/explorer.js']
    assert 'history.pushState' in script
    assert "addEventListener('wheel'" not in script
    assert 'function place(' not in script
