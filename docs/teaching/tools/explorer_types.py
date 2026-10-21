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
