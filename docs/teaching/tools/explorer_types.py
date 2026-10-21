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


def describe_sizes(nodes):
    """Measure linked UTF-8 source text, never an estimated runtime payload."""
    from explorer_documents import REPO

    for node in nodes:
        document = node.get('document', '')
        if not document.startswith('../../../../'):
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
        label = 'Source excerpt' if excerpt else 'Source file'
        if node.get('source_only'):
            label = 'Definition excerpt' if excerpt else 'Definition file'
        node['source_size'] = dict(bytes=len(raw), chars=len(content),
                                   lines=len(content.splitlines()), label=label)


def describe_message_estimates(nodes):
    """Offline examples: no real folders, setup facts, identities or messages."""
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import patch
    from yoke_core.domain import global_orientation
    from yoke_core.domain.main_agent_packet import render_main_agent_block
    from yoke_core.hooks.session_launch_attestation import render_launch_instructions
    from yoke_core.hooks.session_broker_wake import _render

    examples = {}
    orientation = []
    for count in (0, 5):
        folders = [f'/example/workspace/projects/project-{i}' for i in range(count)]
        with patch.object(global_orientation, '_project_folders', return_value=folders):
            orientation.append(global_orientation.render_global_orientation(
                'example-session'.ljust(36, '-'), Path('/example/workspace'),
                setup_lines=[] if not count else ['Setup: ' + 'example status ' * 20]))
    examples['hook:global:orientation'] = (
        orientation, 'Synthetic session and folder; zero to five project folders and zero to 300 characters of setup. Not a guaranteed limit.')
    startup = render_main_agent_block(include_advisories=False)
    examples['hook-block:render_main_agent_block'] = (
        [startup], 'Core message with no installation advisories; conditional notices add bytes.')
    examples['hook:project:orientation'] = (
        ['Your Session: ' + '0' * 36 + '\nRoot: /example/workspace/project\n' + startup,
         'Your Session: ' + '0' * 36 + '\nRoot: /example/workspace/project\n' + startup + 'x' * 600],
        'Representative identity and root plus startup core; zero to 600 extra characters for setup, Git metadata and notices. Not a limit.')
    wake = [_render(SimpleNamespace(lease_id='0' * 36, command='x' * n))[0] for n in (40, 180)]
    examples['hook-block:_render'] = (wake, 'Synthetic lease ID; supplied command between 40 and 180 ASCII characters. Not a limit.')
    launch = render_launch_instructions(SimpleNamespace(
        launch_id='0' * 36, message_id='0' * 36, sender_actor_id=1, body=''))
    examples['hook-block:render_launch_instructions'] = (
        [launch], 'Empty instructions body with synthetic IDs; add the actual body size. No fixed upper bound.')
    for node in nodes:
        if node['id'] not in examples:
            continue
        samples, assumptions = examples[node['id']]
        counts = [len(sample.encode('utf-8')) for sample in samples]
        low, high = min(counts), max(counts)
        amount = f'{low:,}–{high:,} B' if low != high else f'{low:,} B + variable content'
        node['message_estimate'] = dict(label='Estimated message · ' + amount,
                                        assumptions=assumptions)
