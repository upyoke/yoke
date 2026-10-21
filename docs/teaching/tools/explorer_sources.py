"""Editorial navigation over canonical surfaces, not a second teaching inventory."""

SOURCES = (
    {
        "id": "website", "title": "Website & documentation", "stage": "Start",
        "timing": "When someone reads it", "mark": "↗",
        "summary": "The public introduction, install instructions and deeper manual.",
        "delivery": "A person or agent opens a page; its content enters the conversation when read.",
        "surfaces": ("docs-landing", "manual-overview", "manual-contents",
                     "category-summary", "detail-home"),
    },
    {
        "id": "setup", "title": "Install & setup replies", "stage": "Start",
        "timing": "During installation", "mark": "↓",
        "summary": "Questions, choices and the next action, one command reply at a time.",
        "delivery": "Without a terminal, the installer starts agent setup and prints its first question. Each answer resumes the saved setup.",
        "surfaces": ("setup-agent", "setup-install", "setup-tui",
                     "machine-admission", "connection-recovery"),
    },
    {
        "id": "hooks", "title": "Hooks & orientation", "stage": "Enter a session",
        "timing": "At supported harness events", "mark": "↳",
        "summary": "Current machine or project facts, then guidance as events happen.",
        "delivery": "Installed hooks run at supported events. Global orientation applies outside a project; project orientation adds the current project context. Installing a hook is separate from receiving its output.",
        "surfaces": ("global-orientation", "global-hooks", "project-orientation",
                     "project-hooks", "resume-context", "global-native"),
    },
    {
        "id": "rules", "title": "Project rules", "stage": "Enter a session",
        "timing": "When the harness loads the project", "mark": "≡",
        "summary": "AGENTS.md supplies standing obligations and pointers to operation rules.",
        "delivery": "Project installation provides the managed AGENTS.md block. The harness loads native project instructions according to its own discovery rules; a session may need restarting after installation.",
        "surfaces": ("project-native",),
    },
    {
        "id": "skills", "title": "Skills & agent roles", "stage": "Enter a session",
        "timing": "Discovered first; read when used", "mark": "◇",
        "summary": "A discoverable menu of ways to work, with instructions behind each entry.",
        "delivery": "Skill metadata makes an entry discoverable; its instructions are read when invoked. The global yoke-global skill is available outside projects; full Yoke skills belong to installed projects.",
        "surfaces": ("skills-roles", "agent-help"),
    },
    {
        "id": "help", "title": "Command help & packets", "stage": "Work",
        "timing": "When the agent asks for detail", "mark": "?",
        "summary": "A tree of commands and focused context for the operation at hand.",
        "delivery": "Root help leads to a command group, then an operation. Topic packets supply the relevant agent reference when explicitly fetched.",
        "surfaces": ("terminal-help", "packets-help"),
    },
    {
        "id": "feedback", "title": "Command results", "stage": "Work",
        "timing": "After an operation", "mark": "←",
        "summary": "What happened, what is needed next, or how to recover from a refusal.",
        "delivery": "An operation returns its result into the agent's tool context. This continues after setup and can carry relevant next-action teaching.",
        "surfaces": ("command-feedback",),
    },
    {
        "id": "instructions", "title": "Scoped instructions", "stage": "Work",
        "timing": "At a configured work boundary", "mark": "⌁",
        "summary": "Rules for this kind of work, delivered when their scope applies.",
        "delivery": "Execution-instruction records select their scope and delivery points, such as creation, item reads or stage entry.",
        "surfaces": ("execution-instructions",),
    },
    {
        "id": "project", "title": "Project knowledge", "stage": "Work",
        "timing": "When the work needs it", "mark": "▤",
        "summary": "The project's own documentation, routed to the agents doing the work.",
        "delivery": "Project context routes point to relevant existing documents. These keep their project owner and are read for the work that needs them.",
        "surfaces": ("project-hub",),
    },
    {
        "id": "workbench", "title": "Workbench cues", "stage": "Work",
        "timing": "When a person visits the UI", "mark": "▦",
        "summary": "Visible state and next steps in Yoke's dashboard.",
        "delivery": "People encounter cues while using the workbench. UI text does not automatically become agent context.",
        "surfaces": ("workbench-cues",),
    },
)

STAGES = {
    "Start": "Begin with the public entry point and a conversation with setup.",
    "Enter a session": "Yoke becomes available to the harness, then context is received.",
    "Work": "More context arrives when a task, command or person needs it.",
}
