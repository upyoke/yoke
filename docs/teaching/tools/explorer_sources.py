"""Agreed source boxes and editorial placement of the existing teaching records."""

SOURCES = (
    ('homepage', 'Website homepage', 'The introduction to Yoke at upyoke.com.'),
    ('docs', 'Public docs', 'One set of Yoke guides, delivered on the website and inside installed projects.'),
    ('setup', 'Install and setup', 'Instructions, questions and recovery while getting Yoke ready.'),
    ('global-hooks', 'Global hook messages', 'What Yoke tells the agent outside a Yoke project.'),
    ('project-hooks', 'Project hook messages', 'What Yoke tells the agent at events inside a Yoke project.'),
    ('rules', 'AGENTS.md', 'Shared Yoke rules, plus this repository’s additions outside the managed block.'),
    ('skills', 'Skills', 'Procedures the agent reads when using a Yoke skill.'),
    ('roles', 'Agent role instructions', 'Responsibilities and working instructions for each assigned role.'),
    ('help', 'Command help', 'The help tree: root, command groups, then individual operations.'),
    ('feedback', 'Command results and error messages', 'Outcome explanations, next steps and recovery instructions.'),
    ('packets', 'Context packets', 'Focused references the agent requests before particular work.'),
    ('instructions', 'Scoped execution instructions', 'Saved rules delivered when their project or work scope applies.'),
    ('project', 'Project documentation', 'Yoke repository guides and runbooks, shown as project-specific examples.'),
)

# id, title, parent, summary: intermediate branches are navigation, not new facts.
BRANCHES = (
    ('doc-content', 'The docs', 'source:docs', 'The shared overview, categories and documents.'),
    ('web-docs', 'Website docs page', 'source:docs', 'Public guides read at upyoke.com/docs.'),
    ('installed-docs', 'Installed docs (.yoke/docs)', 'source:docs', 'The same public guides, available in an installed project.'),
    ('agent-setup', 'Agent-mode replies', 'source:setup', 'Setup returns questions, choices and the next action to the agent.'),
    ('terminal-setup', 'Interactive terminal screens', 'source:setup', 'A person works through setup directly in their terminal.'),
    ('shared-setup', 'Setup reply format', 'source:setup', 'JSON states returned by agent-mode setup.'),
    ('project-skills', 'Project skills', 'source:skills', 'Skills available in a project where Yoke is installed.'),
)

SURFACE_PARENTS = {
    'docs-landing': 'branch:web-docs',
    'manual-overview': 'branch:doc-content',
    'manual-contents': 'branch:doc-content',
    'category-summary': 'branch:doc-content',
    'detail-home': 'branch:doc-content',
    'setup-agent': 'branch:agent-setup',
    'setup-tui': 'branch:terminal-setup',
    'setup-install': 'branch:shared-setup',
    'machine-admission': 'branch:shared-setup',
    'connection-recovery': 'branch:shared-setup',
    'global-orientation': 'source:global-hooks',
    'global-hooks': 'source:global-hooks',
    'project-orientation': 'source:project-hooks',
    'project-hooks': 'source:project-hooks',
    'project-native': 'source:rules',
    'skills-roles': 'source:skills',
    'agent-help': 'source:skills',
    'resume-context': 'source:skills',
    'terminal-help': 'source:help',
    'command-feedback': 'source:feedback',
    'packets-help': 'source:packets',
    'execution-instructions': 'source:instructions',
    'project-hub': 'source:project',
}

SURFACE_TITLES = {
    'global-orientation': 'First introduction outside a project',
    'global-hooks': 'Messages during work outside a project',
    'project-orientation': 'First introduction inside a project',
    'project-hooks': 'Messages during project work',
    'skills-roles': 'Common skill instructions',
    'resume-context': 'Instructions for continuing work',
    'packets-help': 'What a context packet provides',
    'project-native': 'Standing project instructions',
}

EXCLUDED_SURFACES = {
    'workbench-cues': 'Owned by the dashboard prototype.',
    'global-native': 'Abandoned startup-message proposal; not part of the current map.',
}

SKILL_GROUPS = {
    'Direction and adoption': 'yoke strategize onboard steer feed charge',
    'Define and plan work': 'idea refine shepherd amend',
    'Implement and deliver': 'dash blitz conduct implement implementing polish simulate usher approve',
    'Maintain and learn': 'help doctor curate resync models wrapup',
}
ROLE_GROUPS = {
    'Plan and design': 'product-manager product-designer architect',
    'Build': 'engineer',
    'Review and verify': 'boss simulator tester tester-browser qa-walker',
}

# Named cross-source connections, distinct from topic similarity.
CONNECTIONS = (
    ('branch:install-human', 'branch:terminal-setup', 'Continue to interactive setup'),
    ('branch:install-agent', 'branch:agent-setup', 'Continue to agent setup'),
    ('branch:ask-agent', 'branch:install-command', 'Agent follows the website install route'),
    ('branch:install-command', 'branch:agent-setup', 'Agent mode → structured setup replies'),
    ('branch:install-command', 'branch:terminal-setup', 'Interactive mode → terminal setup screens'),
    ('branch:agent-setup', 'branch:shared-setup', 'Returns the shared setup reply format'),
    ('branch:terminal-setup', 'branch:shared-setup', 'Returns the shared setup reply format'),
    ('branch:agent-setup', 'source:global-hooks', 'After machine setup → global context'),
    ('branch:terminal-setup', 'source:global-hooks', 'After machine setup → global context'),
    ('source:global-hooks', 'skill:yoke-global', 'Choose or add the project'),
    ('skill:yoke-global', 'source:project-hooks', 'Open a session in the project folder'),
    ('source:project-hooks', 'source:rules', 'Project session also loads standing rules'),
    ('source:rules', 'branch:installed-docs', 'Read the relevant operation home'),
    ('source:rules', 'source:project', 'Load the project’s own guidance'),
    ('source:skills', 'source:roles', 'Delegated work supplies a role mandate'),
    ('source:skills', 'source:instructions', 'Load instructions for the current work'),
    ('source:skills', 'source:packets', 'Request focused working context'),
    ('source:skills', 'source:help', 'Check the command recipe before acting'),
    ('source:help', 'source:feedback', 'Run the command → read its result'),
    ('source:feedback', 'source:help', 'Recovery points to exact command help'),
    ('source:instructions', 'source:project', 'Project guidance supplies scoped rules'),
    ('branch:web-docs', 'branch:doc-content', 'Browse the docs'),
    ('branch:web-docs', 'doc:docs/public/index.md', 'Displays on entry'),
    ('branch:installed-docs', 'branch:doc-content', 'Contains the docs'),
)


HOOK_LIFECYCLE = ('SessionStart', 'UserPromptSubmit', 'PreToolUse',
                  'PermissionRequest', 'PostToolUse', 'PostToolUseFailure', 'Stop', 'SessionEnd')


def order_nodes(nodes):
    """Reading order follows encounter/lifecycle; source prose keeps its own order."""
    source_order = ('homepage', 'docs', 'setup', 'global-hooks', 'rules', 'project-hooks',
                    'project', 'skills', 'roles', 'instructions', 'packets', 'help', 'feedback')
    sequences = {
        None: ['source:' + key for key in source_order],
        'source:help': ['command:yoke', 'branch:command-groups'],
        'source:setup': ['installer:script', 'branch:agent-setup', 'branch:terminal-setup', 'branch:shared-setup'],
        'source:skills': ['skill:yoke-global', 'branch:project-skills'],
        'source:docs': ['branch:web-docs', 'branch:installed-docs', 'branch:doc-content'],
    }
    for scope in ('global', 'project'):
        prefix = 'hook-event:' + ('global:' if scope == 'global' else '')
        sequences['source:' + scope + '-hooks'] = [prefix + event for event in HOOK_LIFECYCLE]
    for groups, prefix, parent_prefix in (
        (SKILL_GROUPS, 'skill:', 'branch:project-skills:'),
        (ROLE_GROUPS, 'role:', 'source:roles:'),
    ):
        for title, members in groups.items():
            slug = title.lower().replace(' ', '-')
            sequences[parent_prefix + slug] = [prefix + member for member in members.split()]

    import re
    from explorer_documents import REPO
    paths = re.findall(r'path:\s*["\']?([^"\',\s}]+)', (REPO / 'docs/public/nav.yaml').read_text())
    manual_order = {path: index for index, path in enumerate(paths)}

    def rank(node):
        sequence = sequences.get(node['parent'], [])
        if node['id'] in sequence:
            return sequence.index(node['id'])
        if sequence:
            return len(sequence)
        if node['id'].startswith('docs-category:'):
            path = node['id'].removeprefix('docs-category:') + '/index.md'
            return manual_order.get(path, len(paths))
        if node['id'].startswith('doc:docs/public/') and ':topic:' not in node['id'] and ':passage:' not in node['id']:
            return manual_order.get(node['id'].removeprefix('doc:docs/public/'), len(paths))
        if 'order' in node:
            return node['order']
        if node['id'].startswith(('skill-file:', 'role-file:')):
            return 100000
        if node.get('document_lines') and not node.get('source_only'):
            return node['document_lines'][0]
        return node.get('order', 0)

    # Sorting this flat inventory controls sibling order only, not parentage.
    nodes.sort(key=rank)
