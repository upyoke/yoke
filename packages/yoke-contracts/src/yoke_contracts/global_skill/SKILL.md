---
name: yoke-global
description: "Yoke outside a project: machine status, pick or add the project to work on, and the folder where a new session does the work. Use when this session's folder is not inside a Yoke project."
---

# Yoke outside a project

Yoke is installed on this machine, but this session's folder is not inside a
Yoke project. Item work (ideas, plans, code, reviews) happens in a session
opened in the project's own folder; there the project's full `/yoke` skill
takes over. This skill gets the user there.

## 1. Check the machine

```text
yoke status
```

It names the connection, signed-in actor and any repair to make first.
Outside a project it also warns `project_mapping_missing`; that is expected
here. Do not register this folder as a project. Doctor checks run against
one project: `yoke doctor run --quick --project P`.

## 2. Pick the project

Ask the user what they want to work on, then list the projects:

```text
yoke projects list
```

The session's orientation block lists the project folders on this machine.
A project with no folder here is added in step 3.

## 3. Or add a project

When the work belongs to a project this machine does not have yet, add it
with agent setup. Run it, show the user each question and answer with the
printed `answer_command`; never choose an answer that is theirs to make:

```text
yoke setup --agent
```

Setup clones, imports or creates the project folder and installs Yoke in it.
You approve machine and GitHub codes yourself; only password entry goes to a
person. The full loop is in
<https://upyoke.com/docs/start/agent-setup>.

## 4. Hand over

Tell the user the exact project folder, what they asked for, and to open a
new Claude Code, Codex or Cursor session in that folder. A newly added
project starts with `/yoke onboard` there; an existing one with the request
itself. Yoke never opens that session for them.

## Writing to the user
<!-- BEGIN GENERATED: user-writing -->
Each message to the user is one or two sentences unless they ask for more. Write short, literal, active sentences without idioms; natural questions are fine. Use plain words for ideas and exact names for fields, commands and files; explain an unfamiliar name briefly where it first appears. Never write a bare number or ID: say what it is, e.g. "#411 (soft-launch PR)". When the user must decide, ask one decision at a time, most important first, each with your recommendation. Teach only what they need now, show the action before explaining it, and point to the exact place for more. The sentence limit covers narration; required instructions, recipes and evidence stay complete.
<!-- END GENERATED: user-writing -->

## More help

- Commands: `yoke --help`, then `yoke <command> --help`.
- Product docs: <https://upyoke.com/docs>.
