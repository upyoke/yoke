"""Read curated teaching terms and connect them to the Sources view."""
import json
from model import MODEL_ROOT


def add_terms(nodes, model):
    root = dict(id='view:index', title='Index', parent=None, view='index',
                summary='Draft terms, short definitions and their current sources.',
                node_type='group', type_label='Term index', type_hint='Curated teaching model',
                guidance_scope='repository', scope_label='Repository')
    nodes.append(root)
    sources = {}
    for node in nodes:
        if node.get('document') and not node.get('document_lines'):
            path = node['document'].removeprefix('../../../')
            sources.setdefault(path, node['id'])
    seen = set()
    records = []
    for path in sorted((MODEL_ROOT / 'terms').glob('*.json')):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            key, title, definition = record['id'], record['term'], record['definition']
            if not all(isinstance(v, str) and v.strip() for v in (key, title, definition)):
                raise ValueError('id, term and definition must be nonempty strings')
            if key != path.stem or title.casefold() in seen:
                raise ValueError('filename must match id and terms must be unique')
            if record['status'] != 'draft' or not record['sources']:
                raise ValueError('draft status and at least one source are required')
            missing = [value for value in record['sources'] if value not in sources]
            if missing:
                raise ValueError('sources absent from Sources: ' + ', '.join(missing))
            seen.add(title.casefold())
            records.append(dict(id='term:' + key, title=title, parent=root['id'],
                summary=definition, body='Current documentation for this term:',
                related=[sources[value] for value in record['sources']],
                node_type='concept', type_label='Term', type_hint='Curated definition',
                status_label='Draft', guidance_scope='repository', scope_label='Repository'))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            model.problem('TERM_RECORD_INVALID', str(path.relative_to(MODEL_ROOT)),
                          str(exc) + '; repair the term record and rebuild')
    nodes.extend(sorted(records, key=lambda node: node['title'].casefold()))
