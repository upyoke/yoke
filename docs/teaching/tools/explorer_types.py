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
SURFACE_TYPES = {
    'docs-landing': ('page', 'Docs page', 'Website navigation and entry routes'),
    'manual-overview': ('page', 'Overview article', 'Public explanation of Yoke'),
    'manual-contents': ('group', 'Contents index', 'Navigation across the public guides'),
    'category-summary': ('page', 'Category page', 'Introduces a family of topics'),
    'detail-home': ('page', 'Topic article', 'The full explanation of one topic'),
    'setup-agent': ('reply', 'Agent setup replies', 'Structured questions and answer commands'),
    'setup-tui': ('screen', 'Terminal screens', 'Setup presented to a person'),
    'setup-install': ('reply', 'Installer output', 'Tool checks and installation recovery'),
    'machine-admission': ('screen', 'Authorization flow', 'Connect a person or machine'),
    'connection-recovery': ('reply', 'Recovery output', 'Diagnostics and repair actions'),
    'global-orientation': ('hook', 'Hook introduction', 'Initial context outside a project'),
    'global-hooks': ('hook', 'Hook injections', 'Context delivered at global session events'),
    'project-orientation': ('hook', 'Hook introduction', 'Initial project-session context'),
    'project-hooks': ('hook', 'Hook injections', 'Context delivered at project session events'),
    'project-native': ('file', 'Rules-file overview', 'Describes AGENTS.md and native adapters'),
    'skills-roles': ('group', 'Shared skill guidance', 'Instructions common to procedures'),
    'agent-help': ('reply', 'Agent explanation', 'An answer to the person’s request'),
    'resume-context': ('group', 'Resume guidance', 'Instructions for continuing work'),
    'terminal-help': ('command-group', 'Help overview', 'Describes what command help teaches'),
    'command-feedback': ('reply', 'Command replies', 'Result, refusal and recovery text'),
    'packets-help': ('packet', 'Packet overview', 'Describes fetched working context'),
    'execution-instructions': ('rule', 'Scoped rules', 'Instructions tied to a delivery point'),
    'project-hub': ('file', 'Document index', 'Routes into project-owned knowledge'),
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
GUIDANCE_LABELS = {
    'page': 'Article summary', 'group': 'Guidance summary', 'reply': 'Reply guidance',
    'screen': 'Screen guidance', 'hook': 'Hook guidance', 'file': 'File guidance',
    'command-group': 'Help guidance', 'packet': 'Packet guidance', 'rule': 'Rule summary',
}


def describe_nodes(nodes, commands):
    """Attach types without claiming a research summary is a captured payload."""
    parents = {node['parent'] for node in nodes}
    for node in nodes:
        key = node['id']
        kind, label, hint = 'group', 'Conceptual group', 'Organizes related nodes'
        if key.startswith('source:') and not node['parent']:
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
        elif key.startswith('topic:'):
            kind, label, hint = 'concept', 'Concept', 'Explanation · public documentation'
        elif key.startswith('teaching:'):
            owner = key.split(':', 1)[1].split('/')[0]
            family, _, _ = SURFACE_TYPES[owner]
            kind, label = family, GUIDANCE_LABELS[family]
            hint = 'Teaching summary · not a captured runtime payload'
            if key == 'teaching:packets-help/01':
                kind, label = 'command-group', 'Help guidance'
            elif key in {'teaching:skills-roles/02', 'teaching:skills-roles/04'}:
                kind, label = 'file', 'Role guidance'
        elif key.startswith('surface:') and node.get('record'):
            kind, label, hint = SURFACE_TYPES[key.split(':', 1)[1]]
        elif key.startswith('branch:') and key.split(':', 1)[1] in BRANCH_TYPES:
            kind, label, hint = BRANCH_TYPES[key.split(':', 1)[1]]
        node.update(node_type=kind, type_label=label, type_hint=hint)
