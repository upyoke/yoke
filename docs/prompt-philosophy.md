# Prompt Philosophy

> Canonical source for shared prompt doctrine across Yoke agents and skills.

> **Field-note channel.** Agents log recipe gaps and minor bug observations → `/yoke curate` clusters the signals → operator fixes the source. The directive block below is mirrored verbatim everywhere agents read instructions.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Be The Giant

`Be the giant` means we are never starting from nothing.

We stand on the shoulders of prior generations, prior operators, prior sessions, prior agents, inherited code, inherited docs, and inherited decisions. What we achieve is possible because they gave us a leg up. Their work is the giant beneath us.

Our responsibility is to extend that giant. We do that by leaving work so complete that the next person starts higher instead of from the ground. A good artifact does not merely record what we did. It gives the next reader leverage.

That leverage has a hard boundary: live code and current-state docs must explain themselves without the planning artifacts that produced them. Tickets, strategy docs, plans, phases, task numbers, and acceptance-criterion labels disappear into history. The repository remains. Agents must translate planning context into codebase-reader language before naming, writing, coding, documenting, or commenting.

In Yoke, that means:

- A spec should let the Architect plan without re-investigating basics.
- A technical plan should let the Engineer implement without guessing interfaces or blast radius.
- A dispatch prompt should let a cold-start subagent act with confidence.
- Code, tests, comments, and current-state docs should describe the current function, purpose, mechanics, and domain role to a reader who cannot see the ticket or plan.
- Commits should let the Tester and reviewer verify without reconstructing intent.
- A verdict or simulation report should let the next fixer act mechanically.
- A wrapup should let the next session resume with momentum instead of archaeology.

The doctrine is not just about being helpful. It is an obligation to compound inherited leverage. We received a leg up; we owe the next agent one too.

## Canonical Short Form

Use this short form in prompt surfaces that need the doctrine in-line:

`**Be the giant.** Assume future codebase readers will not have the ephemeral planning artifacts; make this artifact cold-start complete and name live code/docs by current function, purpose, and mechanics.`

Keep the role-specific follow-on sentence after that opener so the doctrine stays tailored to the artifact being produced.

## Writing Guidance

- Keep the full metaphor here, not repeated everywhere.
- Use the short form in agents, skills, and phase files.
- Turn the doctrine into structure when possible: validators, explicit checklists, output contracts, and health checks beat slogans.
