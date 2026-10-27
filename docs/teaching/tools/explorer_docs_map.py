"""Build a proposed page tree from authored teaching-model records."""
import json
from model import MODEL_ROOT
from explorer_docs_coverage import mapping_coverage
from explorer_public_pages import apply_public_page


def map_node(key, title, parent, summary):
    return dict(id=key, title=title, parent=parent, summary=summary,
                node_type='page', type_label='Public page', type_hint='Public documentation structure',
                guidance_scope='repository', scope_label='Public docs', status_label='Draft')


def add_docs_map(nodes, model):
    source_ids = {n['id'] for n in nodes}
    records = {}
    for path in sorted((MODEL_ROOT / 'docs-map').glob('*.json')):
        try:
            record = apply_public_page(json.loads(path.read_text(encoding='utf-8')))
            key = record['id']
            if key != path.stem or key in records:
                raise ValueError('id must match filename and be unique')
            for field in ('title', 'route', 'audience', 'purpose'):
                if not isinstance(record[field], str) or not record[field].strip():
                    raise ValueError(field + ' must be a nonempty string')
            if record['kind'] not in ('overview', 'detail') or record['status'] != 'draft':
                raise ValueError('expected draft overview or detail page')
            for field in ('outline', 'terms', 'commands', 'sources', 'deeper_pages', 'open_questions'):
                if not isinstance(record[field], list) or any(not isinstance(x, str) for x in record[field]):
                    raise ValueError(field + ' must be a list of strings')
            if not record['outline'] or not (record['route'] == '/docs' or record['route'].startswith('/docs/')):
                raise ValueError('outline and proposed /docs/ route required')
            refs = ['term:' + term for term in record['terms']] + record['commands'] + record['sources']
            missing = [ref for ref in refs if ref not in source_ids]
            if missing:
                raise ValueError('unknown references: ' + ', '.join(missing))
            if any(not c.startswith('command:') for c in record['commands']):
                raise ValueError('commands must reference command nodes')
            records[key] = record
        except (OSError, ValueError, TypeError, KeyError) as exc:
            model.problem('DOCS_MAP_INVALID', str(path.relative_to(MODEL_ROOT)), str(exc))
    routes = set()
    for key, record in records.items():
        if record['route'] in routes:
            model.problem('DOCS_MAP_ROUTE', key, 'proposed route is duplicated')
        routes.add(record['route'])
        refs = record['deeper_pages'] + ([record['parent']] if record['parent'] else [])
        if any(ref not in records for ref in refs):
            model.problem('DOCS_MAP_PARENT', key, 'parent or deeper page does not exist')
        seen, current = set(), key
        while current in records:
            if current in seen:
                model.problem('DOCS_MAP_CYCLE', key, 'page parents form a cycle')
                break
            seen.add(current)
            current = records[current]['parent']
    if model.problems:
        return
    root = map_node('view:docs-map', 'Docs map', None,
                    'Public pages and their related terms, commands, and teaching sources. Titles and topics come from the public docs.')
    root.update(view='docs-map', type_label='Documentation plan')
    pages = []
    for key, record in sorted(records.items(), key=lambda pair: (pair[1].get('position', 0), pair[0])):
        node = map_node('page:' + key, record['title'],
                        'page:' + record['parent'] if record['parent'] else root['id'], record['purpose'])
        spec = dict(record)
        spec['terms'] = ['term:' + term for term in record['terms']]
        spec['deeper_pages'] = ['page:' + page for page in record['deeper_pages']]
        node['page_spec'] = spec
        pages.append(node)
    root['map_coverage'] = mapping_coverage(nodes, pages)
    root['page_count'] = len(pages)
    by_id = {n['id']: n for n in nodes}
    for page in pages:
        spec = page['page_spec']
        for ref in set(spec['terms'] + spec['commands'] + spec['sources']):
            by_id[ref].setdefault('proposed_pages', []).append(page['id'])
    nodes.extend([root, *pages])
