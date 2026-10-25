"""Coverage and documentation links in the same guide as their sources."""
from collections import defaultdict
from fnmatch import fnmatch

from explorer_research import add_node, connect, research_id, source_path


def add_inventories(nodes, pages):
    by_id = {node['id']: node for node in nodes}

    def add(key, title, parent, **values):
        node = add_node(nodes, key, title, parent, **values)
        node['type_label'] = 'Source inventory'
        by_id[key] = node
        return node

    add('inventory:commands', 'Command, function and skill coverage', 'research-index:surfaces')
    connect(by_id, 'source:help', 'inventory:commands', 'Coverage', 'Current registry compared with topic references')
    used = {key: defaultdict(list) for key in ('commands', 'functions', 'skills')}
    for cid, record in pages.m.concepts.items():
        for kind in used:
            for value in record.get(kind, []):
                used[kind][value].append(research_id('concept', cid))
    for kind in used:
        parent = 'inventory:' + kind + ':coverage'
        group = add(parent, kind.title(), 'inventory:commands')
        group['summary'] = f'{len(pages.live.get(kind, []))} registered; {len(used[kind])} referenced by topics.'
        for value in sorted(pages.live.get(kind, [])):
            key = parent + ':' + value
            node = add(key, value, parent)
            node['summary'] = ('Referenced by teaching topics.' if used[kind][value]
                               else 'No teaching topic references this registry entry.')
            for target in used[kind][value]:
                connect(by_id, key, target, 'Topics', 'Explicit registry reference')
                connect(by_id, target, key, 'Registry', 'Explicit registry reference')
            target = ('command:' + value if kind == 'commands' else
                      'skill:' + value.removeprefix('/yoke ') if kind == 'skills' else '')
            connect(by_id, key, target, 'Sources', 'Registered source')
    add('inventory:docs', 'Documentation links', 'research-index:surfaces',
        record='../model/docs-graph.json')
    for source in ('source:docs', 'source:project'):
        connect(by_id, source, 'inventory:docs', 'Coverage', 'Tracked document links and publication areas')
    graph = pages.m.docs_graph
    for area in graph.get('areas', []):
        key = 'inventory:docs:' + area['id']
        node = add(key, area['title'], 'inventory:docs')
        node['summary'] = area['publication']
        for cid in area.get('concepts', []):
            connect(by_id, key, research_id('concept', cid), 'Topics', 'Documentation area mapping')
    add('inventory:docs:unassigned', 'Documents without an assigned area', 'inventory:docs')
    add('inventory:docs:excluded', 'Areas excluded from the documentation graph', 'inventory:docs')
    for index, row in enumerate(graph.get('ungraphed', [])):
        node = add('inventory:docs:excluded:' + str(index), row['include'], 'inventory:docs:excluded')
        node['summary'] = row['reason']
        node['body'] = str(sum(fnmatch(path, row['include']) for path in pages.docs)) + ' matching documents.'
        connect(by_id, node['id'], research_id('gap', row['gap']), 'Gaps', 'Recorded exclusion')
    concrete = defaultdict(list)
    for node in nodes:
        if node.get('document') and not node.get('document_lines'):
            concrete[source_path(node['document'])].append(node['id'])
    incoming = defaultdict(list)
    for path, targets in pages.docs.items():
        for target in targets:
            if target in pages.docs:
                incoming[target].append(path)
    for path, targets in pages.docs.items():
        area = pages.area_of(path)
        excluded = any(fnmatch(path, row['include']) for row in graph.get('ungraphed', []))
        parent = 'inventory:docs:' + (area or ('excluded' if excluded else 'unassigned'))
        key = 'inventory:doc:' + path
        node = add(key, path, parent)
        node.update(url='../../../' + path,
                    summary=f'{len(incoming[path])} incoming links · {len(targets)} outgoing links.')
        for target in concrete[path]:
            connect(by_id, target, key, 'Documentation links', 'Tracked document identity')
            connect(by_id, key, target, 'Sources', 'This document in the source guide')
    for path, targets in pages.docs.items():
        for target in targets:
            connect(by_id, 'inventory:doc:' + path, 'inventory:doc:' + target,
                    'Links to', 'Document hyperlink')
            connect(by_id, 'inventory:doc:' + target, 'inventory:doc:' + path,
                    'Linked from', 'Document hyperlink')


def source_snapshot(nodes, pages):
    """Fingerprint inspected inputs; never present an old research claim as reverified."""
    from datetime import datetime, timezone
    import hashlib
    import json
    from pathlib import Path
    import subprocess
    import sys
    from model import all_records, model_files

    repo = Path(__file__).resolve().parents[3]
    paths = set(model_files())
    paths.update(Path(__file__).parent.glob("*"))
    paths.update(repo / path for path in pages.docs)
    for node in nodes:
        if node.get('document'):
            paths.add(repo / source_path(node['document']))
    for _, _, record in all_records(pages.m):
        paths.update(repo / source_path(path) for path in record.get('sources', []))
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_relative_to(repo) and '.venv' not in path.parts:
                paths.add(path)
    digest = hashlib.sha256()
    count = 0
    for path in sorted(paths):
        if path.is_file() and path.is_relative_to(repo):
            digest.update(str(path.relative_to(repo)).encode())
            digest.update(path.read_bytes())
            count += 1
    digest.update(json.dumps({k: sorted(v) for k, v in pages.live.items()}, sort_keys=True).encode())
    commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = bool(subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True))
    return dict(built_at=datetime.now(timezone.utc).isoformat(), commit=commit,
                dirty=dirty, input_files=count, input_digest=digest.hexdigest())
