"""Visible node forms describe content, independently of research status."""

# family, label, short explanation; families control icons and card treatment.
SOURCE_TYPES = {
    'homepage': ('page', 'Web page', 'Public entry · upyoke.com'),
    'docs': ('page', 'Documentation', 'Web and installed guides'),
    'setup': ('screen', 'Setup flow', 'Interactive screens and agent replies'),
    'global-hooks': ('hook', 'Hook messages', 'Injected outside a project'),
    'project-hooks': ('hook', 'Hook messages', 'Injected during project work'),
    'rules': ('file', 'Rules file', 'AGENTS.md · read by the harness'),
    'skills': ('file', 'Skill library', 'Procedure files loaded on demand'),
    'roles': ('file', 'Role library', 'Instructions assigned to a worker'),
    'help': ('command-group', 'CLI reference', 'Help entry, groups and commands'),
    'feedback': ('reply', 'Command output', 'Results, errors and recovery'),
    'packets': ('packet', 'Fetched context', 'Focused context fetched by the agent'),
    'instructions': ('rule', 'Scoped instructions', 'Rules supplied when their scope applies'),
    'project': ('file', 'Project documents', 'The project’s own knowledge and rules'),
}
BRANCH_TYPES = {
    'doc-content': ('group', 'Document collection', 'One shared set of public documents'),
    'web-docs': ('page', 'Web page', 'upyoke.com/docs'),
    'installed-docs': ('file', 'Installed directory', '.yoke/docs · local documentation'),
    'ask-agent': ('prompt', 'Human request', 'Words you give your agent'),
    'install-command': ('command', 'Shell command', 'Run in a terminal or agent harness'),
    'install-human': ('screen', 'Interactive path', 'A person follows terminal screens'),
    'install-agent': ('reply', 'Agent path', 'An agent reads structured setup replies'),
    'agent-setup': ('reply', 'Agent setup', 'Questions and next actions returned as data'),
    'terminal-setup': ('screen', 'Interactive setup', 'Questions and choices in the terminal'),
}
def describe_nodes(nodes, commands):
    """Attach source forms without claiming definitions are captured payloads."""
    parents = {node['parent'] for node in nodes}
    for node in nodes:
        key = node['id']
        kind, label, hint = 'group', 'Group', 'Contains the named files or entries'
        if node.get('form'):
            kind, label, hint = node.pop('form')
        elif key.startswith('source:') and not node['parent']:
            kind, label, hint = SOURCE_TYPES[key.split(':', 1)[1]]
        elif node.get('document'):
            is_skill = key.startswith('skill:')
            kind, label = 'file', 'Skill file' if is_skill else 'Agent-role file'
            hint = node['document'].removeprefix('../../../../')
        elif key.startswith('command:'):
            command = key.removeprefix('command:')
            if command == 'yoke':
                kind, label = 'command-group', 'Main help'
            elif key in parents:
                kind = 'command-group'
                label = 'Command + group' if command in commands else 'Command group'
            else:
                kind, label = 'command', 'Command'
            hint = command + ' --help'
        elif key.startswith('branch:') and key.split(':', 1)[1] in BRANCH_TYPES:
            kind, label, hint = BRANCH_TYPES[key.split(':', 1)[1]]
        node.update(node_type=kind, type_label=label, type_hint=hint)


def describe_scope(nodes):
    """Scope is separate from form: a document can be shared or repo-specific."""
    by_id = {node['id']: node for node in nodes}
    labels = {'shared': 'All Yoke projects', 'repository': 'Yoke repo only',
              'mixed': 'Shared + repo rules'}

    def scope(node):
        if 'guidance_scope' in node:
            return node['guidance_scope']
        if node['id'] == 'source:rules':
            return 'mixed'
        if node['id'] == 'source:project':
            return 'repository'
        return scope(by_id[node['parent']]) if node['parent'] else 'shared'

    for node in nodes:
        value = scope(node)
        node.update(guidance_scope=value, scope_label=labels[value])
        root = node
        while root.get('parent'):
            root = by_id[root['parent']]
        if root['id'] in ('source:global-hooks', 'source:project-hooks'):
            node['hook_context'] = root['id']
            node['scope_label'] = 'Outside projects' if root['id'] == 'source:global-hooks' else 'Inside a project'


def describe_sizes(nodes):
    """Measure linked UTF-8 source text, never an estimated runtime payload."""
    from explorer_documents import REPO

    for node in nodes:
        if node.get('source_only'):
            continue
        document = node.get('document', '')
        if not document.startswith('../../../../'):
            if node.get('type_label') == 'Text passage':
                prose = node['body']
                node['source_size'] = dict(bytes=len(prose.encode('utf-8')), chars=len(prose),
                                          lines=len(prose.splitlines()), label='Context text')
            continue
        path = REPO / document.removeprefix('../../../../')
        if not path.is_file():
            continue
        raw = path.read_bytes()
        content = raw.decode('utf-8')
        excerpt = node.get('document_lines')
        if excerpt:
            start, end = excerpt
            content = ''.join(content.splitlines(keepends=True)[start:end])
            raw = content.encode('utf-8')
        label = 'Context text' if excerpt else 'Document text'
        node['source_size'] = dict(bytes=len(raw), chars=len(content),
                                   lines=len(content.splitlines()), label=label)



def output_samples(samples, basis, variable=False):
    """Count synthetic output examples, including their terminating newlines."""
    return dict(lines=[min(len(s.splitlines()) for s in samples), max(len(s.splitlines()) for s in samples)],
                bytes=[min(len(s.encode('utf-8')) for s in samples), max(len(s.encode('utf-8')) for s in samples)],
                estimated=True, variable=variable, basis=basis)


def incoming_topic_size(title):
    from yoke_core.hooks.session_message_rendering import _parent_overflow_notice
    identity = 'example-message'.ljust(36, '-')
    examples = {
        'Sender': ['Authenticated sender: Operator\n',
                   'Authenticated sender: Example worker via session ' + 's' * 36 + '\n'],
        'Message body': [''],
        'Reminder': ['', 'Reminder: shown 99 time(s) and still unacknowledged. '
                     'If you already acted on it, acknowledge it now; if not, act on it first.\n'],
        'Read the full message': ['', f'Excerpt only; read the full body with `yoke messages get {identity}`.\n'],
        'Acknowledge': [f'Acknowledge: `yoke messages acknowledge {identity}`\n'],
        'More waiting messages': ['', _parent_overflow_notice(999, 's' * 36) + '\n'],
        'Delivery boundaries': ['=== BEGIN YOKE SESSION MESSAGE DELIVERY '
                                + 'YOKE_SESSION_MESSAGE_LEASE:' + 'l' * 36 + ' ' + identity
                                + ' ===\n=== END YOKE SESSION MESSAGE DELIVERY ===\n'],
    }
    if title not in examples:
        return None
    basis = ('One message, synthetic 36-character IDs; optional notices range from absent to present. '
             'Sender uses short-name and session-name examples; counts up to 999. Not a hard maximum.')
    return output_samples(examples[title], basis, variable=title == 'Message body')


def rollup_output_sizes(nodes):
    """Every node describes consumable text; containers sum children, not source code."""
    by_id = {n['id']: n for n in nodes}
    children = {}
    for node in nodes:
        children.setdefault(node['parent'], []).append(node)
    for node in nodes:
        parent = by_id.get(node['parent'], {})
        if parent.get('hook_module') == 'yoke_core.hooks.session_message_delivery':
            node['output_size'] = incoming_topic_size(node['title'])
        source = node.get('source_size')
        if source:
            node['output_size'] = dict(lines=[source['lines']] * 2, bytes=[source['bytes']] * 2,
                                       estimated=False, variable=False, basis='Exact UTF-8 guidance text. Includes its nested sections once.')

    by_id = {node['id']: node for node in nodes}

    def measure(node):
        if node.get('represents'):
            node['output_size'] = measure(by_id[node['represents']])
        if node.get('output_size'):
            return node['output_size']
        nested = children.get(node['id'], [])
        if nested:
            parts = [measure(child) for child in nested]
            size = dict(aggregated=True, lines=[sum(p['lines'][i] for p in parts) for i in (0, 1)],
                        bytes=[sum(p['bytes'][i] for p in parts) for i in (0, 1)],
                        estimated=any(p['estimated'] for p in parts), variable=any(p['variable'] for p in parts),
                        planning=any(p.get('planning') for p in parts),
                        basis='Sum of child context amounts. Optional parts may not appear together; links are not counted. This is a content inventory, not one delivery.')
        else:
            kind = node.get('node_type', '')
            # Coarse, visibly labelled planning bands for output not yet sampled.
            # Never measure the implementation or mistake map summaries for output.
            lines, count = ([1, 8], [40, 800])
            if kind in ('command', 'command-group'):
                lines, count = [5, 80], [250, 8000]
            elif kind == 'rule':
                lines, count = [2, 25], [120, 2500]
            elif kind == 'action':
                lines, count = [0, 2], [0, 200]
            elif kind == 'packet':
                lines, count = [5, 100], [250, 10000]
            size = dict(lines=lines, bytes=count, estimated=True, variable=False, planning=True,
                        basis='Coarse planning range for this kind of output; not a measured render or a guaranteed limit. Replace with template samples when available.')
        node['output_size'] = size
        return size

    def band(values):
        low, high = values
        return f'{low:,}' if low == high else f'{low:,}–{high:,}'

    for node in nodes:
        size = measure(node)
        prefix = 'Estimated' if size['estimated'] else 'Text'
        if size.get('aggregated'):
            prefix = 'Total estimate' if size['estimated'] else 'Total'
        if size.get('planning'):
            prefix = 'Rough total' if children.get(node['id']) or node.get('represents') else 'Rough estimate'
        unit = 'line' if size['lines'] == [1, 1] else 'lines'
        label = f"{prefix} · {band(size['lines'])} {unit} · {band(size['bytes'])} B"
        if size['variable']:
            label = ('Variable body · lines and bytes' if not size['bytes'][1]
                     else label + ' + variable body')
        node['message_estimate'] = dict(label=label, assumptions=size['basis'])
