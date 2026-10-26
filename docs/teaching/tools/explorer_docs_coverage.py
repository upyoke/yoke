"""Describe mapping coverage without claiming that a source is taught or delivered."""
from collections import defaultdict


def mapping_coverage(nodes, pages):
    by_id = {n['id']: n for n in nodes}
    children = defaultdict(list)
    for node in nodes:
        children[node.get('parent')].append(node['id'])

    def descend(key):
        yield key
        for child in children[key]:
            yield from descend(child)

    def expand(keys):
        return {value for key in keys for value in descend(key)}

    terms = {n['id'] for n in nodes if n['id'].startswith('term:')}
    commands = {n['id'] for n in nodes if n['id'].startswith('command:')
                and n.get('node_type') == 'command'}
    # One source representative per document; exclude extracted sections.
    documents = {}
    for node in nodes:
        if node.get('document') and not node.get('document_lines'):
            documents.setdefault(node['document'], node['id'])
    source_entries = set(documents.values()) | {
        n['id'] for n in nodes if n.get('node_type') in ('hook', 'reply', 'packet', 'screen')
        and not n['id'].startswith(('command:', 'help-output:'))}
    mapped = {key: set() for key in ('terms', 'commands', 'sources')}
    term_pages = defaultdict(list)
    for page in pages:
        spec = page['page_spec']
        selected = expand(spec['sources'])
        referenced_paths = {by_id[key]['document'] for key in selected
                            if by_id[key].get('document') and not by_id[key].get('document_lines')}
        selected |= {documents[path] for path in referenced_paths}
        # Root CLI help is an orientation link, never a mapping of every command.
        command_ids = expand([key for key in spec['commands'] if key != 'command:yoke']) & commands
        page['map_counts'] = dict(terms=len(spec['terms']), commands=len(command_ids),
                                  sources=len(selected & source_entries))
        page['expanded_commands'] = sorted(command_ids)
        page['expanded_sources'] = sorted(selected & source_entries)
        if spec['kind'] != 'detail':
            continue
        mapped['terms'].update(spec['terms'])
        mapped['commands'].update(command_ids)
        mapped['sources'].update(selected & source_entries)
        for term in spec['terms']:
            term_pages[term].append(page['id'])
    all_ids = dict(terms=terms, commands=commands, sources=source_entries)
    coverage = {key: dict(total=len(values), mapped=len(mapped[key] & values),
                          unmapped=sorted(values - mapped[key]))
                for key, values in all_ids.items()}
    coverage['multiple_term_pages'] = {key: value for key, value in term_pages.items() if len(value) > 1}
    coverage['sizing'] = [p['id'] for p in pages if p['page_spec']['kind'] == 'detail' and
                          (p['map_counts']['terms'] > 15 or p['map_counts']['sources'] > 30
                           or p['map_counts']['commands'] > 40)]
    coverage['questions'] = [p['id'] for p in pages if p['page_spec']['open_questions']]
    return coverage
