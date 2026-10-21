"""A single spatial map; zoom reveals children and the canonical record in place."""

import json
from pathlib import Path

from explorer_sources import (
    SOURCES, BRANCHES, SURFACE_PARENTS, SURFACE_TITLES,
    EXCLUDED_SURFACES, TEACHING_PARENTS,
)

ROOT = 'explore/index.html'


def map_nodes(model):
    nodes = []
    assigned = set()

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
    by_id = {node['id']: node for node in nodes}
    by_id['source:homepage']['url'] = 'https://upyoke.com'
    by_id['branch:web-docs']['url'] = 'https://upyoke.com/docs'
    by_id['branch:installed-docs']['related'] = ['branch:doc-content']
    by_id['branch:web-docs']['related'] = ['branch:doc-content']
    for sid, surface in model.surfaces.items():
        if sid in EXCLUDED_SURFACES:
            continue
        if sid not in SURFACE_PARENTS:
            model.problem('EXPLORER_SOURCE', 'tools/explorer_sources.py',
                          f'{sid}: assign this surface to an agreed source')
            continue
        assigned.add(sid)
        add('surface:' + sid, SURFACE_TITLES.get(sid, surface['title']),
            SURFACE_PARENTS[sid], surface.get('encounter', ''), surface['status'], surface)
        for rid in surface['parts']:
            row = model.teaching[rid]
            if row['status'] == 'superseded':
                continue
            node = add('teaching:' + rid, row['title'],
                       TEACHING_PARENTS.get(rid, 'surface:' + sid),
                       '', row['status'], row)
            node['related'] = ['topic:' + cid for cid in row.get('topics', [])]
    add('topics', 'Topics in the public guides', 'branch:doc-content',
        'Explore the shared concept tree; a topic mapping does not prove delivery.')
    repo = Path(__file__).resolve().parents[3]
    for path in sorted((repo / '.agents/skills/yoke').rglob('SKILL.md')):
        name = path.parent.relative_to(repo / '.agents/skills/yoke').as_posix()
        if name == '.':
            name = 'yoke'
        node = add('skill:' + name, name.replace('/', ' / '), 'branch:project-skills',
                   'Read the procedure for this skill.')
        node['document'] = '../../../../' + path.relative_to(repo).as_posix()
    global_docs = 'packages/yoke-contracts/src/yoke_contracts/global_skill/SKILL.md'
    node = add('skill:yoke-global', 'yoke-global (outside projects)', 'source:skills',
               'Check machine status, choose or add a project, then open a session in its folder.')
    node['document'] = '../../../../' + global_docs
    for path in sorted((repo / 'runtime/agents').glob('*.md')):
        title = path.stem.replace('-', ' ').title()
        node = add('role:' + path.stem, title, 'source:roles',
                   'Read the instructions assigned to this agent role.')
        node['document'] = '../../../../' + path.relative_to(repo).as_posix()
    commands = {}
    for cid, row in model.concepts.items():
        add('topic:' + cid, row['title'],
            'topic:' + row['parent'] if row['parent'] else 'topics',
            '', row['status'], row)
        for command in row.get('commands', []):
            commands.setdefault(command, []).append('topic:' + cid)
    prefixes = {'yoke'}
    for command in commands:
        words = command.split()
        prefixes.update(' '.join(words[:n]) for n in range(1, len(words) + 1))
    for command in sorted(prefixes):
        parent = command.rpartition(' ')[0]
        node = add('command:' + command, command,
                   'command:' + parent if parent else 'source:help',
                   'Run ' + command + ' --help for current options and recipes.')
        node['related'] = commands.get(command, [])
    return nodes


def build_explorer(views, pages):
    nodes = map_nodes(pages.m)
    if pages.m.problems:
        return
    # Small model-derived chunks keep generated files within the teaching limit.
    chunks = []
    for offset in range(0, len(nodes), 12):
        name = f'nodes-{offset // 12}.json'
        chunks.append(name)
        views['explore/' + name] = json.dumps(nodes[offset:offset + 12], indent=1) + '\n'
    views['explore/manifest.json'] = json.dumps(chunks, indent=1) + '\n'
    for asset in ('explorer.css', 'explorer.js'):
        views['explore/' + asset] = Path(__file__).with_name(asset).read_text()
    views[ROOT] = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yoke · Context map</title>
<link rel="stylesheet" href="explorer.css">
<script src="explorer.js" defer></script>
</head>
<body>
<header><div><b>yoke</b><span> / context map</span></div>
<span class="review">Structure in review</span></header>
<nav id="trail" aria-label="Map position"></nav>
<div id="map" tabindex="0" role="region" aria-label="Zoomable context map">
<svg id="wires" aria-hidden="true"></svg><div id="world"></div>
</div>
<aside id="intro"><h1>One map. Different depths.</h1>
<p>Zoom into a source to see its branches. Keep going to read a teaching.</p>
<p class="muted">Drag to pan · scroll to zoom · click a node to focus</p></aside>
<div id="tools" aria-label="Map controls">
<button id="out" aria-label="Zoom out">−</button>
<output id="scale">100%</output>
<button id="in" aria-label="Zoom in">+</button>
<button id="up">Up one level</button><button id="home">Whole map</button>
</div>
<p id="notice" role="status">Loading the context map…</p>
<div id="future">Later: search will light up related context paths.</div>
<noscript>This spatial view needs JavaScript. Open the
<a href="../index.html">research catalogue</a> instead.</noscript>
</body></html>
'''
