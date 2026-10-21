"""Concrete files and their real directory/category names for the context map."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def heading(path):
    content = path.read_text()
    match = re.search(r'^# (.+)$', content, re.M)
    return match.group(1).strip() if match else path.stem.replace('-', ' ')


def document(add, key, path, parent, label='Document', title=None):
    relative = path.relative_to(REPO).as_posix()
    node = add(key, title or heading(path), parent, relative)
    node.update(document='../../../../' + relative, form=('file', label, relative))
    return node


def tree(add, paths, root, prefix, base):
    """Use index headings for categories and file headings for documents."""
    paths = set(paths)
    directories = {base}
    for path in paths:
        directories.update(p for p in path.parents if p == base or base in p.parents)
    for directory in sorted(directories, key=lambda p: (len(p.parts), str(p))):
        if directory == base:
            continue
        index = directory / 'index.md'
        key = prefix + directory.relative_to(base).as_posix()
        parent = root if directory.parent == base else prefix + directory.parent.relative_to(base).as_posix()
        title = heading(index) if index in paths else directory.name.replace('-', ' ').title()
        node = add(key, title, parent, directory.relative_to(REPO).as_posix())
        node['form'] = ('group', 'Docs category', node['summary'])
    for path in sorted(paths, key=lambda p: (p.name != 'index.md', str(p))):
        parent = root if path.parent == base else prefix + path.parent.relative_to(base).as_posix()
        title = heading(path)
        if path.name == 'index.md':
            title += ' · overview & contents'
        document(add, 'doc:' + path.relative_to(REPO).as_posix(), path, parent, title=title)


def add_documents(add):
    public = REPO / 'docs/public'
    tree(add, public.rglob('*.md'), 'source:docs', 'docs-category:', public)
    # Concrete repository documents, separate from the installed public manual.
    project = REPO / 'docs'
    paths = [p for p in project.rglob('*.md')
             if p.relative_to(project).parts[0] not in {'public', 'archive', 'teaching'}]
    tree(add, paths, 'source:project', 'project-category:', project)
    for name in ('README.md', 'CONTRIBUTING.md'):
        if (REPO / name).is_file():
            document(add, 'doc:' + name, REPO / name, 'source:project')
    for name, title in (
        ('packages/yoke-core/src/yoke_core/install_bundle_tree/AGENTS.md', 'AGENTS.md · installed Yoke rules'),
        ('AGENTS.md', 'AGENTS.md · this repository'),
    ):
        path = REPO / name
        node = document(add, 'rules:' + name, path, 'source:rules', 'Rules file', title)
        add_sections(add, node, path)


def add_sections(add, node, path):
    """Expose named sections of a real file without inventing prose categories."""
    lines = path.read_text().splitlines()
    starts = [(i, line[3:]) for i, line in enumerate(lines) if line.startswith('## ')]
    for number, (start, title) in enumerate(starts):
        end = starts[number + 1][0] if number + 1 < len(starts) else len(lines)
        child = add(node['id'] + ':section:' + str(start), title, node['id'], path.name)
        child.update(document=node['document'], document_lines=[start, end],
                     form=('file', 'File section', node['summary']))


def connect_document_links(nodes):
    """Resolve actual Markdown links to other mapped documents and commands."""
    ids = {node['id'] for node in nodes}
    for node in nodes:
        if not node.get('document') or node.get('document_lines'):
            continue
        path = REPO / node['document'].removeprefix('../../../../')
        if path.suffix != '.md':
            continue
        targets = set()
        for link in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            destination = (path.parent / link.split('#')[0]).resolve()
            if destination.is_relative_to(REPO):
                target = 'doc:' + destination.relative_to(REPO).as_posix()
                if target in ids and target != node['id']:
                    targets.add(target)
        node['related'] = sorted(targets)
