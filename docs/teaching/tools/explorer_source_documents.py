"""Concrete Pack, decision and repository documents missing from the source guide."""
import json
from collections import defaultdict

from inventory import tracked_files
from explorer_documents import REPO, document, tree


def group(add, key, title, parent, summary):
    node = add(key, title, parent, summary)
    node['form'] = ('group', 'Document collection', summary)
    return node


def add_source_documents(add):
    files = [REPO / name for name in tracked_files() if name.endswith('.md')]
    add_packs(add, files)
    add_decisions(add, files)
    add_repository_documents(add, files)


def add_packs(add, files):
    packs = defaultdict(lambda: defaultdict(list))
    installed = defaultdict(list)
    for path in files:
        parts = path.relative_to(REPO).parts
        if len(parts) > 5 and parts[0] == 'packs' and parts[2] == 'versions':
            packs[parts[1]][parts[3]].append(path)
        elif parts[:2] == ('docs', 'packs') and len(parts) > 3:
            installed[parts[2]].append(path)
    for name in sorted(set(packs) | set(installed)):
        parent = 'pack-docs:' + name
        group(add, parent, name, 'source:packs', 'Guidance supplied by this Pack.')
        if installed[name]:
            key = parent + ':installed'
            group(add, key, 'Installed in this checkout', parent,
                  'The project copy, which can differ from a published Pack version.')
            base = REPO / 'docs/packs' / name
            tree(add, installed[name], key, key + ':', base)
        if packs[name]:
            versions = parent + ':versions'
            group(add, versions, 'Versioned source', parent,
                  'Open a version to read its bundled documents and templates.')
            for version, paths in sorted(packs[name].items()):
                key = versions + ':' + version
                group(add, key, version, versions, 'Pack version ' + version)
                base = REPO / 'packs' / name / 'versions' / version
                # Remove packaging folders from display, preserving document identity.
                docs = base / 'files/docs/packs' / name
                guides = [p for p in paths if p.is_relative_to(docs)]
                tree(add, guides, key, key + ':guide:', docs)
                rest = [p for p in paths if p not in guides]
                if rest:
                    templates = key + ':templates'
                    group(add, templates, 'Other bundled documents', key,
                          'Documentation and templates outside the Pack guide folder.')
                    tree(add, rest, templates, templates + ':', base)


def add_decisions(add, files):
    current = group(add, 'decisions:current', 'Current decisions', 'source:decisions',
                    'Approved teaching decisions and current repository decision files.')
    for path in sorted((REPO / 'docs/teaching/model/boundaries').glob('*.json')):
        record = json.loads(path.read_text())
        if record.get('status') != 'approved':
            continue
        node = add('decision:' + record['id'], record['title'], current['id'], record['text'])
        node.update(record='../model/boundaries/' + path.name, research=True,
                    status_label='Approved teaching decision',
                    form=('file', 'Decision record', 'Canonical teaching-model record'))
    base = REPO / 'docs/decisions'
    tree(add, [p for p in files if p.is_relative_to(base)], current['id'],
         'current-decisions:', base)
    historical = group(add, 'decisions:history', 'Historical decisions', 'source:decisions',
                       'Archived reasoning; inspect current guidance before relying on it.')
    base = REPO / 'docs/archive/decisions'
    tree(add, [p for p in files if p.is_relative_to(base)], historical['id'],
         'historical-decisions:', base)


def add_repository_documents(add, files):
    collections = (
        ('packages', 'Package documentation'),
        ('runtime/harness', 'Harness documentation'),
        ('runtime/api', 'API documentation'),
        ('events', 'Event catalog'),
        ('packaging', 'Release packaging'),
        ('brand', 'Brand guidance'),
        ('ouroboros', 'Learning records'),
        ('docs/archive', 'Archived project documentation'),
    )
    for folder, title in collections:
        base = REPO / folder
        paths = [p for p in files if p.is_relative_to(base)
                 and 'install_bundle_tree' not in p.parts
                 and 'global_skill' not in p.parts
                 and not p.is_relative_to(REPO / 'runtime/harness/claude/agents')
                 and not p.is_relative_to(REPO / 'docs/archive/decisions')]
        if not paths:
            continue
        key = 'repository-docs:' + folder
        group(add, key, title, 'source:project',
              'Repository-owned documents from ' + folder + '.')
        tree(add, paths, key, key + ':', base)
    for name in ('LICENSE.md', 'CLA.md'):
        path = REPO / name
        if path in files:
            document(add, 'doc:' + name, path, 'source:project')
