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
    tree(add, public.rglob('*.md'), 'branch:doc-content', 'docs-category:', public)
    # Concrete repository documents, separate from the installed public manual.
    project = REPO / 'docs'
    paths = [p for p in project.rglob('*.md')
             if p.relative_to(project).parts[0] not in {'public', 'archive', 'teaching'}]
    tree(add, paths, 'source:project', 'project-category:', project)
    for name in ('README.md', 'CONTRIBUTING.md'):
        if (REPO / name).is_file():
            document(add, 'doc:' + name, REPO / name, 'source:project')
    add_rules(add)


def rule_topics(add, path, start, end, scope):
    lines = path.read_text().splitlines()
    headings = [(i, re.sub(r'^#+ ', '', line)) for i, line in enumerate(lines)
                if start <= i < end and re.match(r'^#{1,2} ', line)
                and line != '# Yoke — Project Rules']
    if not headings or headings[0][0] > start:
        headings.insert(0, (start, 'Rule loading and field notes'))
    for index, (first, title) in enumerate(headings):
        last = headings[index + 1][0] if index + 1 < len(headings) else end
        content = re.sub(r'<!--.*?-->', '', '\n'.join(lines[first:last]), flags=re.S).strip()
        if not content:
            continue
        relative = path.relative_to(REPO).as_posix()
        node = add('rules-topic:' + scope + ':' + str(first), title, 'source:rules',
                   'Shipped by Yoke' if scope == 'shared' else 'Added by the Yoke repository')
        node.update(document='../../../../' + relative, document_lines=[first, last],
                    guidance_scope=scope, form=('file', 'Rules topic', relative))


def add_rules(add):
    shipped = REPO / 'packages/yoke-core/src/yoke_core/install_bundle_tree/AGENTS.md'
    project = REPO / 'AGENTS.md'
    template = shipped.read_text().splitlines()
    local = project.read_text().splitlines()
    begin = '<!-- BEGIN YOKE MANAGED BLOCK -->'
    end = '<!-- END YOKE MANAGED BLOCK -->'
    # The shipped preamble also contains portable field-note guidance.
    rule_topics(add, shipped, 0, template.index(end), 'shared')
    if local[:local.index(begin)] != template[:template.index(begin)]:
        rule_topics(add, project, 0, local.index(begin), 'repository')
    rule_topics(add, project, local.index(end) + 1, len(local), 'repository')


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


def expand_prose_topics(nodes):
    """Give long Markdown leaves a contents layer using their own headings or paragraphs."""
    parents = {node['parent'] for node in nodes}
    for node in list(nodes):
        document = node.get('document', '')
        if node['id'] in parents or node.get('source_only') or not document.endswith('.md'):
            continue
        lines = (REPO / document.removeprefix('../../../../')).read_text().splitlines()
        first, last = node.get('document_lines', [0, len(lines)])
        text = re.sub(r'<!--.*?-->', '', '\n'.join(lines[first:last]), flags=re.S)
        if len(text.split()) < 80:
            continue
        starts, fenced = [], False
        for index in range(first, last):
            line = lines[index]
            if line.startswith(('```', '~~~')):
                fenced = not fenced
            match = re.match(r'^(#{1,6}) (.+)', line)
            if match and not fenced and index > first:
                starts.append((index, len(match[1]), match[2]))
        if starts:
            level = min(depth for _, depth, _ in starts)
            starts = [(index, title) for index, depth, title in starts if depth == level]
            if starts[0][0] > first + 2:
                starts.insert(0, (first, 'Introduction'))
            for offset, (start, title) in enumerate(starts):
                end = starts[offset + 1][0] if offset + 1 < len(starts) else last
                nodes.append(dict(id=node['id'] + ':topic:' + str(start), parent=node['id'],
                                  title=title, summary='', document=document, document_lines=[start, end],
                                  form=('section', 'Text section', 'Section of ' + node['title'])))
        else:
            paragraphs = [part.strip() for part in re.split(r'\n\s*\n', text) if part.strip()]
            for offset, paragraph in enumerate(paragraphs):
                if paragraph.startswith(('#', '```', '~~~', '<!--')):
                    continue
                words = re.sub(r'[`*#]', '', paragraph).split()
                title = ' '.join(words[:8]) + ('…' if len(words) > 8 else '')
                nodes.append(dict(id=node['id'] + ':passage:' + str(offset), parent=node['id'],
                                  title=title, summary='', body=paragraph,
                                  form=('section', 'Text passage', 'Passage from ' + node['title'])))
