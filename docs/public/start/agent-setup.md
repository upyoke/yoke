# Agent setup

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Get started](index.md) > Agent setup
<!-- /yoke:breadcrumbs -->

A coding agent (Claude Code, Codex, Cursor or any other) can run `yoke setup`
for a person. In agent mode, setup asks the wizard's own questions one at a
time as JSON lines. The agent shows each question to the person and answers
it with a command.

## When agent mode runs

- Without a terminal, `yoke setup` starts in agent mode by itself. The public
  installer does the same: an agent's `curl … | sh` installs Yoke, then runs
  `yoke setup --agent --post-install` and prints the first question.
- `yoke setup --agent` forces agent mode, even in a terminal.
- `yoke setup --tui` forces the full-screen wizard; without a terminal it
  refuses with `setup_tui_requires_terminal`.
- `--non-interactive` and `--json` keep the one-shot flag path, which takes
  every answer as a flag.

## The loop

1. Run `yoke setup --agent`.
2. Read the last line on stdout. It is one JSON object.
3. When `state` is `question`, show the person `question`, `detail` and the
   `answers` labels. Follow `guidance`. Ask the person; never guess a choice
   that is theirs to make.
4. Run the line's `answer_command` with the chosen value, for example
   `yoke setup --agent --answer project.mode=machine-only`.
5. Repeat until `state` is `done`, then show the person `detail`,
   `install_health` in full and the `next` steps in order.

Answers are saved by question key, so every call resumes where setup stopped.
A bare `yoke setup --agent` repeats the waiting question. Human progress and
wait notices go to stderr; stdout carries only the JSON lines.

```json
{"setup": "agent", "version": 1, "state": "question", "step": "project",
 "key": "project.mode", "question": "Set up a project.", "detail": [],
 "answers": [{"value": "machine-only", "label": "Just this machine", "description": "…"}],
 "input": null, "fields": [], "secret": false, "human": null,
 "guidance": "…", "answer_command": "/Users/me/.local/bin/yoke setup --agent --answer project.mode=<value>"}
```

`answer_command` names the running `yoke` by absolute path, so it works before
the shell reloads PATH.

## Answer shapes

- **A choice:** `--answer KEY=VALUE`, where VALUE is one of `answers[].value`.
- **A typed value:** `input` is set. `--answer KEY=TEXT` runs the screen's own
  check; an empty value takes `input.default`.
- **A form:** `fields` lists `KEY.FIELD` keys. Give one `--answer` per field in
  the same call, plus `--answer KEY=VALUE` when the form also has `answers`.
  An omitted field takes its `default`. If the form has `answers`, a different
  value redraws the form first, so answer its fields in the next call.

Only the waiting question and its fields are accepted. The first call may
answer the first question.

## Browser steps

A line with `state` `browser` carries `human.url`, `human.user_code`,
`human.instructions` and `wait`. Show the person the link and code and ask
them to finish in their browser. Setup never opens a browser in agent mode
and keeps waiting in the same command, so let it run; the next line arrives
once they approve. Device codes and tokens never appear in any line.

## Secrets

A question with `"secret": true` never takes its value through `--answer`.
Take the route its `guidance` names: for a team-server token, answer the
token source `file` and give the token file's path; hosting credentials can be
skipped for now. Or ask the person to finish that step with `yoke setup --tui`.

## Presets, Apply and starting over

Setup flags given to the first agent call (for example `--local` or `--yes`)
are presets, like wizard defaults. Later calls may repeat them or leave them
out; different flags refuse with `setup_agent_flags_changed`. `--yes` answers
the review question with `apply`.

Answering `review.confirm` with `apply` writes the setup and returns `done`.
A failed Apply returns `state` `failed` with `reason` `setup_apply_failed`, the
run report path and the failure question; show the person the cause, then
answer it (`resume`, when offered, continues the same run). Answering a cancel
choice returns `done` with `"cancelled": true` and deletes the saved answers.
`yoke setup --agent --discard` deletes an in-progress agent setup.

## Exit codes, refusals and failures

Exit 0 means the last line is `question`, `browser` or `done`; 1 means
`failed`; 2 means `refused`. Every refusal and failure carries `reason` and
`recovery`. A refusal changes nothing and repeats the waiting question when
there is one.

| reason | what to do |
|---|---|
| `setup_answer_not_current` | answer the repeated question by its key |
| `setup_answer_not_allowed` | use one of `answers[].value` |
| `setup_answer_invalid` | correct the value; `recovery` says why |
| `setup_secret_answer_refused` | take the question's non-secret route |
| `setup_agent_flags_changed` | rerun without flags, or `--discard` |
| `setup_agent_busy` | wait for the other `yoke setup --agent` call |
| `setup_agent_store_unreadable` | run `yoke setup --agent --discard` |
| `setup_tui_requires_terminal` | run in a terminal, or use `--agent` |
| `setup_step_failed` (failed) | fix the named cause, then run `yoke setup --agent` |
| `setup_apply_failed` (failed) | answer the failure question shown with it |

## Optional issue mirroring

When GitHub issue mirroring would help this project, explain that it copies
backlog items and tasks into the repository’s Issues and offer a separate
opt-in after setup. Connecting GitHub or approving setup leaves sync off.
Enable only after the person agrees; otherwise continue with sync off.
Use the [project setting recipe](../github/sync.md#the-per-project-switch-projectsgithub_sync_mode)
to check permissions and enable or change it later. Do not add a wizard
question or ask this during machine-only or no-GitHub setup.

## After setup

`done` lists the next steps: open a new terminal when shell files changed,
then open Claude Code, Codex or Cursor in the project folder and run
`/yoke onboard` there. Yoke never opens that session for the person. A
machine-only setup adds a project later through another `yoke setup --agent`.

`yoke connect --json` and `yoke github connect --json` stay available as
standalone commands for one sign-in outside setup.
