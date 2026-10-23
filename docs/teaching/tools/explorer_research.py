"""Connect canonical teaching records to concrete sources without copying prose."""
from collections import defaultdict
import re

from model import all_records, coverage
from explorer_sources import SURFACE_PARENTS, EXCLUDED_SURFACES

KINDS = {
    'concept': ('Topics', 'Topic'), 'surface': ('Teaching plans', 'Surface research'),
    'teaching': ('Teaching plans', 'Teaching research'),
    'scenario': ('Journeys', 'Journey'), 'lesson': ('Journeys', 'Journey lesson'),
    'boundary': ('Design decisions', 'Design decision'), 'gap': ('Gaps', 'Teaching gap'),
    'evidence': ('Evidence', 'Evidence record'),
}
REFS = {
    'topics': 'concept', 'concepts': 'concept', 'related': 'concept',
    'surfaces': 'surface', 'surface_refs': 'surface',
    'scenarios': 'scenario', 'related_scenarios': 'scenario',
    'boundaries': 'boundary', 'gaps': 'gap',
}
STATUS = {
    'draft-copy': 'Proposal · not shipped wording',
    'candidate': 'Proposal · awaiting approval',
    'approved': 'Approved research decision',
    'observed': 'Source observation · not live delivery proof',
    'verified-live': 'Live verification recorded · see evidence and scope',
    'deferred': 'Planned · deferred', 'superseded': 'Historical · replaced',
}


def research_id(kind, key):
    return 'research:' + kind + ':' + key


def add_node(nodes, key, title, parent=None, **values):
    node = dict(id=key, title=title, parent=parent, summary='', research=True,
                node_type='concept', type_label='Research', type_hint='',
                guidance_scope='research', scope_label='', **values)
    nodes.append(node)
    return node


def connect(by_id, source, target, group, reason):
    if source == target or source not in by_id or target not in by_id:
        return
    edges = by_id[source].setdefault('research_links', {}).setdefault(group, [])
    if not any(edge['target'] == target for edge in edges):
        edges.append(dict(target=target, reason=reason))


def source_path(value):
    return re.sub(r':\d+(?:-\d+)?$', '', value).split('#')[0].removeprefix('../../../../')


def add_research(nodes, model):
    add_node(nodes, 'view:topics', 'Topics', view='topics')['summary'] = (
        'What Yoke teaches, with links to its sources, journeys and research.')
    add_node(nodes, 'view:journeys', 'Journeys', view='journeys')['summary'] = (
        'Recorded situations and lessons, linked to the context needed along the way.')
    add_node(nodes, 'view:research', 'Research', view='research')['summary'] = (
        'Teaching plans, decisions, gaps and evidence. Current source content lives under Sources.')
    collections = {
        'surfaces': 'Teaching plans', 'boundaries': 'Design decisions', 'gaps': 'Gaps',
        'evidence': 'Evidence', 'history': 'History', 'dashboard': 'Dashboard research',
    }
    for key, title in collections.items():
        add_node(nodes, 'research-index:' + key, title, 'view:research')
    records = list(all_records(model))
    direct_coverage = coverage(model)
    by_id = {node['id']: node for node in nodes}
    # Only whole-file identities establish a file match, not arbitrary title similarity.
    files = defaultdict(list)
    for node in nodes:
        if node.get('document') and (not node.get('document_lines') or node.get('source_only')):
            files[source_path(node['document'])].append(node['id'])
    for group in model.evidence_files:
        key = 'research-collection:' + group['id']
        node = add_node(nodes, key, group['title'], 'research-index:evidence')
        node['record'] = '../../model/evidence/' + group['id'] + '.json'
        by_id[key] = node
    for kind, key, record in records:
        rid = research_id(kind, key)
        parent = {
            'concept': research_id('concept', record['parent']) if record.get('parent') else 'view:topics',
            'scenario': 'view:journeys',
            'surface': 'research-index:surfaces',
            'boundary': 'research-index:boundaries', 'gap': 'research-index:gaps',
            'evidence': 'research-collection:' + record.get('page', ''),
            'teaching': research_id('surface', record.get('owner', '')),
            'lesson': research_id('scenario', record.get('owner', '')),
        }[kind]
        if record.get('status') == 'superseded':
            parent = 'research-index:history'
        elif key == 'workbench-cues' and kind == 'surface':
            parent = 'research-index:dashboard'
        node = add_node(nodes, rid, record.get('title', key), parent)
        node.update(record='../../' + record['file'].removeprefix('docs/teaching/'),
                    record_id=key, record_kind=kind, status=record.get('status'),
                    type_label=KINDS[kind][1], status_label=STATUS.get(record.get('status'), ''))
        summary = next((record[k] for k in ('need', 'text', 'current', 'scope', 'when')
                        if isinstance(record.get(k), str)), '')
        node['summary'] = summary[:240] + ('…' if len(summary) > 240 else '')
        if kind == 'concept' and record.get('status') == 'draft-copy':
            node['status_label'] = 'Research outline'
        if kind == 'concept':
            node['coverage'] = len(direct_coverage[key])
        by_id[rid] = node
    surface_targets = dict(SURFACE_PARENTS)
    for sid in model.surfaces:
        if sid not in EXCLUDED_SURFACES and surface_targets.get(sid) not in by_id:
            model.problem('EXPLORER_SOURCE', 'tools/explorer_sources.py',
                          f'{sid}: mapped source node does not exist')
    # Retained historical/dashboard material has a home, never a fabricated live source.
    for kind, key, record in records:
        rid = research_id(kind, key)
        for field, target_kind in REFS.items():
            values = record.get(field, [])
            if isinstance(values, str):
                values = [values]
            for value in values:
                target = research_id(target_kind, value)
                connect(by_id, rid, target, KINDS[target_kind][0], 'Explicit record reference')
                connect(by_id, target, rid, KINDS[kind][0], 'Explicit record reference')
        owner = key if kind == 'surface' else record.get('owner') if kind == 'teaching' else None
        target = surface_targets.get(owner)
        if target in by_id:
            connect(by_id, target, rid, 'Teaching plans', 'Research for this teaching surface')
            connect(by_id, rid, target, 'Sources', 'Mapped teaching surface')
            for topic in record.get('topics', []):
                tid = research_id('concept', topic)
                connect(by_id, target, tid, 'Topics', 'Named by this surface’s teaching research')
                connect(by_id, tid, target, 'Sources', 'Teaching research maps this topic here')
        for field, prefix in (('commands', 'command:'), ('skills', 'skill:')):
            for value in record.get(field, []):
                target = prefix + value.removeprefix('/yoke ')
                connect(by_id, rid, target, 'Sources', 'Named ' + field[:-1])
                connect(by_id, target, rid, KINDS[kind][0], 'Explicit ' + field[:-1] + ' reference')
        for path in record.get('sources', []):
            for target in files.get(source_path(path), []):
                reason = ('Cites the containing source file' if by_id[target].get('document_lines')
                          else 'Cites this source file')
                connect(by_id, rid, target, 'Sources', reason)
                connect(by_id, target, rid, KINDS[kind][0], reason)
    # Every edge is evidence-labelled; shared citations are not proof of a claim.
    citations = defaultdict(list)
    for kind, key, record in records:
        for path in record.get('sources', []):
            citations[source_path(path)].append((kind, research_id(kind, key)))
    for path, related in citations.items():
        evidence = [rid for kind, rid in related if kind == 'evidence']
        for kind, rid in related:
            if kind not in ('gap', 'boundary', 'teaching', 'lesson'):
                continue
            for eid in evidence:
                connect(by_id, rid, eid, 'Related evidence', 'Shares cited file: ' + path)
                connect(by_id, eid, rid, KINDS[kind][0], 'Shares cited file: ' + path)
    for node in nodes:
        if node.get('research_links'):
            for label, links in list(node['research_links'].items()):
                active, historical = [], []
                for edge in links:
                    (historical if by_id[edge['target']].get('status') == 'superseded' else active).append(edge)
                node['research_links'][label] = active
                if historical:
                    node['research_links'].setdefault('History', []).extend(historical)
    return by_id
