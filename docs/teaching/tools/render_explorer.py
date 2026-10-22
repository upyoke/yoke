"""A single spatial map; zoom reveals children and the canonical record in place."""

import json
import hashlib
from pathlib import Path
from functools import lru_cache

from inventory import live_registries
from explorer_types import describe_nodes, describe_scope, describe_sizes, rollup_output_sizes
from explorer_documents import add_documents, add_sections, connect_document_links, document, expand_prose_topics, describe_message_estimates
from explorer_sources import order_nodes
from explorer_runtime import add_setup, add_packets, add_delivery_topics
from explorer_messages import add_hooks, add_replies



from explorer_sources import (
    SOURCES, BRANCHES, SURFACE_PARENTS,
    EXCLUDED_SURFACES,
    SKILL_GROUPS, ROLE_GROUPS, CONNECTIONS,
)

ROOT = 'explore/index.html'


@lru_cache(maxsize=1)
def registered_commands():
    return tuple(live_registries()["commands"])



def map_nodes(model):
    nodes = []

    def group_id(parent, title):
        return parent + ":" + title.lower().replace(" ", "-")

    def add(key, title, parent=None, summary='', status='', record=None):
        node = dict(id=key, title=title, parent=parent, summary=summary, status=status)
        if record:
            node['record'] = '../../' + record['file'].removeprefix('docs/teaching/')
        nodes.append(node)
        return node

    for sid, title, summary in SOURCES:
        add('source:' + sid, title, summary=summary)
    for bid, title, parent, summary in BRANCHES:
        add('branch:' + bid, title, parent, summary)
    add('branch:ask-agent', 'Tell your agent “install upyoke.com”',
        'source:homepage', 'Give this request to your agent; it reads the website and follows the install route.')
    add('branch:install-command', 'Install command', 'source:homepage',
        'curl -fsSL https://upyoke.com/install | sh — people use interactive mode; agents use agent mode.')
    add('branch:install-human', 'For people: interactive mode', 'branch:install-command',
        'Run the install command in a terminal, then follow setup’s interactive screens.')
    add('branch:install-agent', 'For agents: agent mode', 'branch:install-command',
        'The agent runs the installer; agent setup returns its first question and the answer command.')
    for sid in model.surfaces:
        if sid not in EXCLUDED_SURFACES and sid not in SURFACE_PARENTS:
            model.problem('EXPLORER_SOURCE', 'tools/explorer_sources.py',
                          f'{sid}: assign this surface to an agreed source')
    add_documents(add)
    add_setup(add)
    add_packets(add)
    add_hooks(add)
    add_replies(add)
    repo = Path(__file__).resolve().parents[3]
    skill_parents, role_parents = {}, {}
    for groups, parent, mapping in ((SKILL_GROUPS, 'branch:project-skills', skill_parents),
                                    (ROLE_GROUPS, 'source:roles', role_parents)):
        for title, members in groups.items():
            key = group_id(parent, title)
            add(key, title, parent, 'Zoom in to see the individual procedures or roles.')
            mapping.update({member: key for member in members.split()})
    for path in sorted((repo / '.agents/skills/yoke').rglob('SKILL.md')):
        name = path.parent.relative_to(repo / '.agents/skills/yoke').as_posix()
        if name == '.':
            name = 'yoke'
        parent = 'skill:' + name.rpartition('/')[0] if '/' in name else skill_parents.get(name, 'branch:project-skills')
        node = add('skill:' + name, name.replace('/', ' / '), parent,
                   'Read the procedure for this skill.')
        node['document'] = '../../../../' + path.relative_to(repo).as_posix()
        add_sections(add, node, path)
    skill_root = repo / '.agents/skills/yoke'
    for path in sorted(skill_root.rglob('*.md')):
        if path.name == 'SKILL.md':
            continue
        owner = next((p for p in path.parents if (p / 'SKILL.md').is_file()), skill_root)
        name = owner.relative_to(skill_root).as_posix()
        key = 'skill:yoke' if name == '.' else 'skill:' + name
        document(add, 'skill-file:' + path.relative_to(skill_root).as_posix(), path, key, 'Skill reference')
    global_docs = 'packages/yoke-contracts/src/yoke_contracts/global_skill/SKILL.md'
    node = add('skill:yoke-global', 'yoke-global (outside projects)', 'source:skills',
               'Check machine status, choose or add a project, then open a session in its folder.')
    node['document'] = '../../../../' + global_docs
    for path in sorted((repo / 'runtime/agents').glob('*.md')):
        title = path.stem.replace('-', ' ').title()
        node = add('role:' + path.stem, title, role_parents.get(path.stem, 'source:roles'),
                   'Read the instructions assigned to this agent role.')
        node['document'] = '../../../../' + path.relative_to(repo).as_posix()
        add_sections(add, node, path)
    role_ids = {node['id'] for node in nodes}
    for path in sorted((repo / 'runtime/agents').glob('*/*.md')):
        if 'role:' + path.parent.name not in role_ids:
            add('role:' + path.parent.name, path.parent.name.strip('_').title() + ' role files',
                'source:roles', 'Files shared by agent role instructions.')
            role_ids.add('role:' + path.parent.name)
        document(add, 'role-file:' + path.relative_to(repo / 'runtime/agents').as_posix(),
                 path, 'role:' + path.parent.name, 'Role reference')
    from io import StringIO
    from yoke_cli.commands.command_tree import render_root_help
    from yoke_cli.commands.group_help import emit_group_help_if_available
    commands = set(registered_commands())
    prefixes = {'yoke'}
    for command in commands:
        words = command.split()
        prefixes.update(' '.join(words[:n]) for n in range(1, len(words) + 1))
    add('branch:command-groups', 'Command groups', 'source:help',
        'Browse named groups, their help output, subgroups and individual commands.')
    for command in sorted(prefixes):
        parent = command.rpartition(' ')[0]
        is_group = any(value.startswith(command + ' ') for value in prefixes)
        node = add('command:' + command, command,
                   ('source:help' if command == 'yoke' else 'branch:command-groups'
                    if parent == 'yoke' else 'command:' + parent),
                   'Run ' + command + ' --help for current options and recipes.')
        if command == 'yoke':
            node.update(title='yoke --help', body=render_root_help(),
                        form=('reply', 'Main help', 'Actual root help output'))
        elif is_group:
            output = StringIO()
            emit_group_help_if_available(command.split()[1:] + ['--help'], stream=output)
            help_node = add('help-output:' + command, command + ' --help', node['id'],
                            'The help output for this command group.')
            help_node.update(body=output.getvalue(), order=-1,
                             form=('reply', 'Group help output', command + ' --help'))
        else:
            continue
        output_node = node if command == 'yoke' else help_node
        content = output_node['body']
        output_node['output_size'] = dict(lines=[len(content.splitlines())] * 2,
            bytes=[len(content.encode())] * 2, estimated=False, variable=False,
            basis='Rendered by the CLI help formatter; UTF-8 output.')
        marker = ('Categories and actions (open --help for each):' if command == 'yoke'
                  else 'Immediate children (open --help for recipes and options):')
        intro, separator, rest = content.partition(marker)
        listing, gap, guidance = rest.partition('\n\n')
        for key, title, prose in (('usage', 'Usage and getting started', intro),
                                   ('children', 'Available commands', separator + listing),
                                   ('guidance', 'Options and guidance', guidance)):
            if not prose.strip():
                continue
            child = add(output_node['id'] + ':text:' + key, title, output_node['id'])
            child.update(body=prose.strip(), form=('section', 'Help text', title),
                         output_size=dict(lines=[len(prose.splitlines())] * 2,
                         bytes=[len(prose.encode())] * 2, estimated=False, variable=False,
                         basis='Section of rendered help output.'))
    nodes = list({node['id']: node for node in nodes}.values())
    nodes.sort(key=lambda n: (n['id'] != 'doc:docs/public/index.md', n.get('order', 0)))
    by_id = {node['id']: node for node in nodes}
    by_id['source:rules']['document'] = '../../../../AGENTS.md'
    by_id['source:homepage']['url'] = 'https://upyoke.com'
    by_id['branch:web-docs']['url'] = 'https://upyoke.com/docs'
    for location in ('web-docs', 'installed-docs'):
        by_id['branch:' + location]['related'] = ['branch:doc-content']
    connect_document_links(nodes)
    for source, target, label in CONNECTIONS:
        by_id[source].setdefault('connections', []).append(dict(target=target, label=label))
    add_delivery_topics(nodes)
    expand_prose_topics(nodes)
    order_nodes(nodes)
    describe_nodes(nodes, set(registered_commands()))
    describe_scope(nodes)
    describe_sizes(nodes)
    describe_message_estimates(nodes)
    for alias, target in (('branch:install-human', 'branch:terminal-setup'),
                          ('branch:install-agent', 'branch:agent-setup')):
        by_id[alias]['represents'] = target
        by_id[alias]['connections'] = []
    rollup_output_sizes(nodes)
    return nodes


def build_explorer(views, pages):
    nodes = map_nodes(pages.m)
    if pages.m.problems:
        return
    # Small model-derived chunks keep generated files within the teaching limit.
    chunks = []
    batch = []
    for node in nodes:
        if batch and (len(batch) >= 12 or len(json.dumps(batch + [node])) > 14000):
            name = f'nodes-{len(chunks)}.json'
            chunks.append(name)
            views['explore/' + name] = json.dumps(batch, separators=(',', ':')) + '\n'
            batch = []
        batch.append(node)
    if batch:
        name = f'nodes-{len(chunks)}.json'
        chunks.append(name)
        views['explore/' + name] = json.dumps(batch, separators=(',', ':')) + '\n'
    views['explore/manifest.json'] = json.dumps(chunks) + '\n'
    for asset in ('explorer.css', 'explorer.js', 'explorer_graph.js'):
        views['explore/' + asset] = Path(__file__).with_name(asset).read_text()
    views[ROOT] = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yoke · Context map</title>
<link rel="stylesheet" href="explorer.css">
<script src="explorer_graph.js" defer></script>
<script src="explorer.js" defer></script>
</head>
<body>
<header><a class="brand" href="index.html" aria-label="Yoke context map"><span class="brand-mark">y</span>yoke<span class="brand-divider">/</span><span class="brand-name">Context map</span></a>
<div class="header-actions"><button id="trace" aria-pressed="false">Show connections</button><span class="review">Design preview</span></div></header>
<aside id="sources" aria-label="Teaching sources"><div class="rail-title">Explore</div><nav id="source-list"></nav><div class="rail-foot"><span class="live-dot"></span> A map of what teaches Yoke<br><small>Sources → instructions → connections</small></div></aside>
<nav id="trail" aria-label="Map position"></nav>
<div id="map" tabindex="0" role="region" aria-label="Zoomable context map">
<svg id="wires" aria-hidden="true"></svg><div id="world"></div>
</div>
<aside id="intro"><h1>How Yoke learns to work.</h1>
<p>Every instruction has a home. Explore the sources and follow what connects them.</p>
<p class="muted">Select a source to explore inside. Hover to trace its connections.</p></aside>
<div id="tools" aria-label="Map controls">
<button id="out" aria-label="Zoom out">−</button>
<output id="scale">100%</output>
<button id="in" aria-label="Zoom in">+</button>
<button id="up">Up one level</button><button id="home">Whole map</button>
</div>
<aside id="connections" aria-label="Connections" hidden></aside>
<p id="notice" role="status">Loading the context map…</p>
<div id="future">Drag to pan <span>·</span> Scroll to zoom <span>·</span> Esc to go back</div>
<noscript>This spatial view needs JavaScript. Open the
<a href="../index.html">research catalogue</a> instead.</noscript>
</body></html>
'''
    for asset in ('explorer.css', 'explorer.js', 'explorer_graph.js'):
        version = hashlib.sha256(views['explore/' + asset].encode()).hexdigest()[:12]
        stem, suffix = asset.rsplit('.', 1)
        versioned = stem + '-' + version + '.' + suffix
        views['explore/' + versioned] = views['explore/' + asset]
        views[ROOT] = views[ROOT].replace('"' + asset + '"', '"' + versioned + '"')
