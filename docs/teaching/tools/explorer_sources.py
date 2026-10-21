"""Agreed source boxes and editorial placement of the existing teaching records."""

SOURCES = (
    ('homepage', 'Website homepage', 'The introduction to Yoke at upyoke.com.'),
    ('docs', 'Public docs', 'One set of Yoke guides, delivered on the website and inside installed projects.'),
    ('setup', 'Install and setup', 'Instructions, questions and recovery while getting Yoke ready.'),
    ('global-hooks', 'Global hook messages', 'What Yoke tells the agent outside a Yoke project.'),
    ('project-hooks', 'Project hook messages', 'What Yoke tells the agent at events inside a Yoke project.'),
    ('rules', 'Project rules (AGENTS.md)', 'Standing Yoke and project rules loaded by the harness.'),
    ('skills', 'Skills', 'Procedures the agent reads when using a Yoke skill.'),
    ('roles', 'Agent role instructions', 'Responsibilities and working instructions for each assigned role.'),
    ('help', 'Command help', 'The help tree: root, command groups, then individual operations.'),
    ('feedback', 'Command results and error messages', 'Outcome explanations, next steps and recovery instructions.'),
    ('packets', 'Context packets', 'Focused references the agent requests before particular work.'),
    ('instructions', 'Scoped execution instructions', 'Saved rules delivered when their project or work scope applies.'),
    ('project', 'Project documentation', 'The project’s own guides, conventions, architecture notes and runbooks.'),
)

# id, title, parent, summary: intermediate branches are navigation, not new facts.
BRANCHES = (
    ('web-docs', 'Website docs page', 'source:docs', 'Public guides read at upyoke.com/docs.'),
    ('installed-docs', 'Installed docs (.yoke/docs)', 'source:docs', 'The same public guides, available in an installed project.'),
    ('doc-content', 'Shared documentation content', 'source:docs', 'The overview, navigation, topic articles and concept tree behind both locations.'),
    ('agent-setup', 'Agent-mode replies', 'source:setup', 'Setup returns questions, choices and the next action to the agent.'),
    ('terminal-setup', 'Interactive terminal screens', 'source:setup', 'A person works through setup directly in their terminal.'),
    ('shared-setup', 'Shared setup guidance', 'source:setup', 'Install checks, machine connection and recovery used across setup routes.'),
    ('project-skills', 'Project skills', 'source:skills', 'Skills available in a project where Yoke is installed.'),
    ('skill-guidance', 'How skills guide work', 'source:skills', 'Common instructions, including what to reload when continuing work.'),
    ('role-guidance', 'How roles guide work', 'source:roles', 'Shared responsibilities for delegated agents.'),
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
    'skills-roles': 'branch:skill-guidance',
    'agent-help': 'branch:skill-guidance',
    'resume-context': 'branch:skill-guidance',
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

# Split mixed legacy records according to the agreed source, without copying them.
TEACHING_PARENTS = {
    'skills-roles/02': 'branch:role-guidance',
    'skills-roles/04': 'branch:role-guidance',
    'packets-help/01': 'surface:terminal-help',
}
