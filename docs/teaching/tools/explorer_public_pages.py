"""Read public-owned page titles, routes, and headings into the teaching map."""
from pathlib import Path
import posixpath
from markdown_it import MarkdownIt

PUBLIC = Path(__file__).resolve().parents[2] / 'public'


def public_page_path(key):
    if key == 'start':
        return 'index.md'
    if key == 'reference':
        return 'guide/reference/index.md'
    return f'guide/{key}.md'


def apply_public_page(record):
    """Teaching associations supplement the actual public page, never own it."""
    path = public_page_path(record['id'])
    source = PUBLIC / path
    if not source.is_file():
        raise ValueError(f'public page missing: docs/public/{path}')
    tokens = MarkdownIt().parse(source.read_text())
    related = []
    for token in tokens:
        for child in token.children or []:
            if child.type != 'link_open':
                continue
            href = child.attrGet('href') or ''
            if ':' in href or href.startswith(('/', '#')):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), href.split('#')[0]))
            if target.startswith('guide/') and target.endswith('.md'):
                key = target.removeprefix('guide/').removesuffix('.md').removesuffix('/index')
                if key != record['id'] and key not in related:
                    related.append(key)
    record['deeper_pages'] = related
    topics = []
    outline = []
    parents = {}
    for i, token in enumerate(tokens):
        if token.type != 'heading_open':
            continue
        level = int(token.tag[1:])
        title = tokens[i + 1].content
        if level == 1:
            record['title'] = title
        elif level == 2:
            outline.append(title)
            parents = {2: title}
            topics.append({'title': title, 'outline': []})
        elif parents:
            parent = parents.get(level - 1)
            if parent:
                next(t for t in topics if t['title'] == parent)['outline'].append(title)
            topics.append({'title': title, 'outline': []})
            parents = {k: v for k, v in parents.items() if k < level}
            parents[level] = title
    route = path.removesuffix('.md').removesuffix('/index')
    record['route'] = '/docs' if path == 'index.md' else '/docs/' + route
    record['outline'] = outline
    record['topics'] = [t for t in topics if t['outline']]
    record['public_source'] = 'docs/public/' + path
    source_id = 'doc:' + record['public_source']
    if source_id not in record['sources']:
        record['sources'].append(source_id)
    return record
