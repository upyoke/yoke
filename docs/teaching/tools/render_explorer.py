"""Build the unified responsive teaching guide from sources and research."""

import json
from pathlib import Path
from functools import lru_cache

from inventory import live_registries
from explorer_types import describe_nodes, describe_scope, describe_sizes, rollup_output_sizes
from explorer_documents import add_documents, add_sections, connect_document_links, document, expand_prose_topics, describe_message_estimates
from explorer_sources import order_nodes
from explorer_runtime import add_setup, add_packets
from explorer_delivery import add_delivery_topics
from explorer_messages import add_hooks, add_replies



from explorer_sources import (
    SOURCES, BRANCHES, SURFACE_PARENTS,
    EXCLUDED_SURFACES,
    SKILL_GROUPS, ROLE_GROUPS, CONNECTIONS,
)

PAGE = 'yokepedia.html'
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
VIEWS = HERE.parent / 'views'
SCRIPTS = ('explorer_graph.js', 'explorer_research.js', 'explorer.js')


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
            node['record'] = '../' + record['file'].removeprefix('docs/teaching/')
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
    repo = REPO
    skill_parents, role_parents = {}, {}
    for groups, parent, mapping in ((SKILL_GROUPS, 'branch:project-skills', skill_parents),
                                    (ROLE_GROUPS, 'source:roles', role_parents)):
        for title, members in groups.items():
            key = group_id(parent, title)
            add(key, title, parent, 'Open a procedure or role to read its instructions.')
            mapping.update({member: key for member in members.split()})
    for path in sorted((repo / '.agents/skills/yoke').rglob('SKILL.md')):
        name = path.parent.relative_to(repo / '.agents/skills/yoke').as_posix()
        if name == '.':
            name = 'yoke'
        parent = 'skill:' + name.rpartition('/')[0] if '/' in name else skill_parents.get(name, 'branch:project-skills')
        node = add('skill:' + name, name.replace('/', ' / '), parent,
                   'Read the procedure for this skill.')
        node['document'] = '../../../' + path.relative_to(repo).as_posix()
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
    node['document'] = '../../../' + global_docs
    for path in sorted((repo / 'runtime/agents').glob('*.md')):
        title = path.stem.replace('-', ' ').title()
        node = add('role:' + path.stem, title, role_parents.get(path.stem, 'source:roles'),
                   'Read the instructions assigned to this agent role.')
        node['document'] = '../../../' + path.relative_to(repo).as_posix()
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
    by_id['source:rules']['document'] = '../../../AGENTS.md'
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
    """Add the page to ``views``; return the generated text to privacy-scan.

    Embedded documents and records are verbatim copies of tracked files whose
    owners scan them, so the scan covers the shell, each node and build data.
    """
    from explorer_research import add_research
    from explorer_inventory import add_inventories, source_snapshot

    nodes = map_nodes(pages.m)
    if pages.m.problems:
        return {}
    add_research(nodes, pages.m)
    add_inventories(nodes, pages)
    if pages.m.problems:
        return {}
    data = dict(nodes=nodes, documents=embedded_documents(nodes, pages.m),
                records=embedded_records(nodes, pages.m),
                build=source_snapshot(nodes, pages))
    if pages.m.problems:
        return {}
    views[PAGE] = page_html(data, pages.m)
    scanned = {PAGE: page_html(dict(nodes=[], documents={}, records={}, build={}), pages.m),
               PAGE + '#build': embed_json(data['build'])}
    scanned.update((PAGE + '#' + node['id'], embed_json(node)) for node in nodes)
    return scanned


def embedded_documents(nodes, model):
    """Full source text for every document node, keyed by its link."""
    documents = {}
    for link in dict.fromkeys(node['document'] for node in nodes if node.get('document')):
        path = REPO / link.removeprefix('../../../')
        try:
            documents[link] = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:
            model.problem('GUIDE_SOURCE_UNREADABLE', path.relative_to(REPO).as_posix(),
                          f'{exc}; restore the file or stop citing it, then rebuild')
    return documents


def embedded_records(nodes, model):
    """Every canonical research record, keyed by its link from the page."""
    records = {}
    for link in dict.fromkeys(node['record'] for node in nodes if node.get('record')):
        path = (VIEWS / link).resolve()
        try:
            records[link] = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            model.problem('GUIDE_SOURCE_UNREADABLE', path.relative_to(REPO).as_posix(),
                          f'{exc}; restore the record, then rebuild')
    return records


def embed_json(value):
    """JSON safe inside a script element: no less-than character survives."""
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')


def page_html(data, model):
    """One self-contained page: inline style, scripts and embedded data."""
    css = HERE.joinpath('explorer.css').read_text(encoding='utf-8')
    scripts = [HERE.joinpath(name).read_text(encoding='utf-8') for name in SCRIPTS]
    for name, text in [('explorer.css', css), *zip(SCRIPTS, scripts)]:
        for unsafe in ('</style', '</script', '<!--'):
            if unsafe in text.lower():
                model.problem('GUIDE_ASSET_UNSAFE', 'tools/' + name,
                              f'contains {unsafe}, which can end its inline element; '
                              'build that text from parts, then rebuild')
    inline = ''.join(f'<script>\n{text}</script>\n' for text in scripts)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yokepedia</title>
<style>
{css}</style>
<script id="yokepedia-data" type="application/json">{embed_json(data)}</script>
</head>
<body>
<header class="site-header"><a class="brand" href="{PAGE}">yoke <span>Yokepedia</span></a><span class="review">Design preview</span></header>
<nav id="view-nav" aria-label="Browse teaching"></nav>
<div class="page-layout">
<aside id="sources" aria-label="Teaching sources"><div class="rail-title">Sources</div><nav id="source-list"></nav></aside>
<main id="main"><nav id="trail" aria-label="Breadcrumbs"></nav><div id="world"></div>
<p id="notice" role="status">Loading sources…</p>
<details id="build-info" class="research"><summary>Source freshness</summary></details>
<aside id="connections" aria-label="Related sources" hidden></aside>
<noscript>Yokepedia needs JavaScript. Canonical records remain in docs/teaching/model.</noscript>
</main></div>
{inline}</body></html>
"""
