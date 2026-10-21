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

# A group owns a coherent question; unlisted records remain at their source.
TEACHING_GROUPS = {
    'setup-agent': {
        'Start or resume setup': '01 02 03 setup-facts backup-start desired-02',
        'Answer questions and authorize access': 'browser-steps desired-01 04 desired-03',
        'Check readiness and enter a project': '05 06 install-health server-health desired-04',
        'Adopt the project and begin work': '07 desired-05',
    },
    'setup-tui': {
        'Choose how and where to run': '01 03 backup-start desired-01',
        'Connect people and repositories': '02 04 browser-steps repository-access desired-02',
        'Navigate screens and apply choices': '06 back-navigation text-wrapping apply-progress desired-03',
        'Finish or recover': '05 failure-recovery board-art desired-04',
    },
    'global-orientation': {
        'Know this machine and connection': '01 04 06 machine-setup-facts desired-04',
        'Choose a project or continue globally': '02 03 05 desired-01 desired-02 desired-03',
    },
    'global-hooks': {
        'Registration and connection health': '01 diagnostics evaluator-readiness',
        'Messages and next actions': '02 03 desired-02',
        'Which rules apply here': '04 desired-01',
    },
    'project-orientation': {
        'Identify the session and readiness': '01 02 setup-facts desired-01 desired-02',
        'Find the next useful work': '03 04 05 desired-03 desired-04',
    },
    'project-hooks': {
        'Check actions and explain blockers': '01 02 destructive-git-scope recursive-delete-scope desired-01',
        'Deliver timely context': '03 04 05 desired-02',
        'Hook health and reporting': 'diagnostics control-plane-transport',
    },
    'project-native': {
        'Authority, scope and safe changes': '01 02 desired-01 desired-03',
        'Load the right instructions': '03 04 desired-02 desired-04',
        'Communicate and continue work': '05 06 desired-05',
    },
    'command-feedback': {
        'Read outcomes and larger results': '01 02 bounded-replies deployment-run-reads desired-01 desired-03',
        'Understand refusals and repair them': '03 04 browser-admission project-selection settings desired-02',
        'Install, setup and cleanup': 'setup-next-action immutable-cli-updates project-uninstall universe-retention',
        'Work, data and delivery': 'spec-input db-read-item-refs deployment-qa-wait deployment-read-deadline',
    },
    'packets-help': {
        'Schemas and supported capabilities': '02 04 desired-03',
        'Choose the context needed for work': '03 desired-01 desired-02 setup-facts spec-input migration-composition',
    },
    'execution-instructions': {
        'Scope and delivery timing': '01 02 04 desired-01',
        'Read, maintain and adopt instructions': '03 desired-02 desired-03 onboard-proposal',
    },
    'project-hub': {
        'Understand the project and direction': '01 02 desired-02',
        'Find existing project knowledge': '03 desired-01',
        'Build, test and operate the project': '04 05 desired-03',
    },
    'terminal-help': {
        'Start and choose the right context': '01 02 03 config-selection',
        'Browse commands and exact recipes': '04 command-tree desired-01 desired-02 desired-03',
        'Find deeper explanations': '05',
    },
    'resume-context': {
        'Reload the work and instructions': '01 02 desired-01',
        'Recheck changes and continue': '03 04 desired-02 desired-03',
    },
    'skills-roles': {
        'Enter a procedure and load context': '01 03 desired-01 desired-02 action-only-bodies',
        'Begin or hand off work': '05 desired-03 setup-next-action spec-input worktree-preparation',
        'Verify and finish': 'desired-04 consumer-proof migration-composition qa-execution-adoption qa-execution-reconcile',
    },
    'agent-help': {
        'Understand the request and choose a route': '01 02 03 04 desired-01 desired-02 desired-03 topic-routing',
        'Run and wait for checks': 'headless-command-time-limit remote-ci-wait-end-turn remote-test-selection source-gate-continuation',
    },
}

SKILL_GROUPS = {
    'Direction and adoption': 'yoke strategize onboard steer feed charge',
    'Define and plan work': 'idea refine shepherd amend',
    'Implement and deliver': 'dash blitz conduct implement implementing polish simulate usher approve',
    'Maintain and learn': 'help doctor curate resync models wrapup',
}
ROLE_GROUPS = {
    'Plan and design': 'architect product-designer product-manager',
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
    ('branch:agent-setup', 'branch:shared-setup', 'Uses shared install and connection checks'),
    ('branch:terminal-setup', 'branch:shared-setup', 'Uses shared install and connection checks'),
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
    ('branch:web-docs', 'branch:doc-content', 'Reads the shared public guides'),
    ('branch:installed-docs', 'branch:doc-content', 'Reads the shared public guides'),
)
