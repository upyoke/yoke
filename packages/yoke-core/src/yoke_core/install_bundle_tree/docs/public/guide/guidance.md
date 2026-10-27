# Agent guidance

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Agent guidance
<!-- /yoke:breadcrumbs -->

Yoke gives agents the instructions and context they need as work progresses. Shared repository rules establish the basics; skills describe procedures; hooks and focused context packets bring current guidance into a session when it is relevant.

Use [Execution instructions](execution-instructions.md) for your own project-specific conventions, constraints, reminders, and procedures tied to workflow stages.

## Skills and agent roles

### Choosing a skill

A skill is an agent-readable procedure for a kind of work. For example, `/yoke onboard` helps adopt a project, `/yoke strategize` supports a strategy conversation, and `/yoke steer` coordinates work from a plan. Other skills carry items through their workflow segments.

Your agent follows the skill appropriate to the current task and stage. A skill provides the steps and required context; it does not replace the shared records or workflow checks that determine whether a step is allowed.

### Roles in planning, implementation, and review

Different roles focus on different responsibilities, such as product definition, design, implementation, or review. A workflow can involve several roles without asking every session to load every role's instructions.

Roles and execution levels are separate. A role describes the job; a level helps select model capability and effort. See [Steering and fleet control](sessions.md).

### Skill references versus CLI commands

A slash-skill name is an instruction to the coding agent. A `yoke ...` command is an operation the agent runs through the CLI. They may refer to related work but are not interchangeable syntax.

The [agent command guide](../agents/commands.md) lists user-facing skill entry points. The [maintenance guide](../agents/maintenance-commands.md) covers maintenance procedures, and [Command and technical reference](reference/index.md) leads to CLI details.

## Hooks, packets, and repository rules

### Harness-specific discovery

Yoke installs shared project instructions in `AGENTS.md` and a canonical skill tree under `.agents/skills/yoke/`. Each supported harness has a discovery mechanism, with additional configuration where required.

Project install and refresh check that the harness can find the intended instructions without silently replacing unrelated user content. Start the new session named by a setup check when the current harness cannot load newly installed hooks in place.

See [Native instruction and skill discovery](../agents/harness-discovery.md) for supported surfaces and troubleshooting.

### Session events

Hooks run at harness events such as session activity and tool use. They connect the conversation to Yoke's registration, current work context, and delivery of relevant messages or guidance.

A file being present is not the same as a hook having run in a session. Readiness checks distinguish installed configuration from observed delivery and name the next step when a harness needs attention.

### Focused packets

A context packet is a focused set of operational information an agent requests for its role or current work. Packets let the agent read the relevant rules and recipes without loading the entire documentation corpus into every conversation.

Command replies also teach the next action or recovery at the point it matters. These surfaces complement public docs: the docs explain the system to people, while runtime context supplies the exact current requirements to agents.

### AGENTS.md and project rules

`AGENTS.md` holds shared repository guidance. Yoke manages its own marked block while preserving project-owned material outside it. Installed reference docs provide deeper operation rules when the agent needs them.

Use durable project rules for guidance that always applies. Use scoped execution instructions for guidance that belongs to selected projects, workflows, or stages. Avoid duplicating the same rule across many files, where it can drift or arrive at the wrong time.

See [Projects](configuration.md) for installation and settings, and [Execution instructions](execution-instructions.md) for scoped context.
