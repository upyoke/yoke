# Terminal help and replies

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [CLI and config](index.md) > Help and replies
<!-- /yoke:breadcrumbs -->

```text
yoke --help
yoke items --help
yoke items get --help
yoke items get APP-7 status title
yoke deployment-runs get RUN-ID status current_stage
yoke session-control launch list --project example
```

Yoke plans, builds, verifies and delivers software with people and agents.
Root help lists immediate categories and actions, including `dash` and `task`.
Category help lists immediate children once, each with a one-line summary.
Command help opens with that summary, shows its usage once, and owns its
supported recipe, arguments, options and prerequisites. Every argument has a
short help line. Reading help performs no work.
A command that also has children shows its children and its action options.
Supported alternate spellings follow the same tree.

`yoke` and `yoke help` open the overview. Before machine setup, bare `yoke`
names the missing machine configuration and its setup recovery. `yoke --help`
remains available. `--env NAME` selects a configured connection and
`--version` prints the installed release.

## Human replies

Default replies label values and table columns, state empty results, and keep
public item references, returned identifiers, facts and warnings. Refusals name
the actual reason and its recovery. Only missing required project selection
reports `project_required`. Access, ambiguity and capability failures retain
their own meanings.

Routine reads use command-specific summary fields and pages. Use the named
field, page or `--full` recipe for detail. JSON output and write receipts
always retain their complete selected result, warnings and recovery.

`deployment-runs get RUN-ID` shows status, current stage and membership counts.
Select named fields (`status current_stage`, `member_items membership_removals`)
for detail; use `--include-member-closure` for member completion blockers, or
`--full` for the complete run. `launch list` shows compact operational and
history rows, with full launch IDs and continuation cursors; `--full` adds
placement, model and registered-session columns. Read one launch with
`yoke session-control launch get LAUNCH-ID --full`.

A function is a read only when its registry entry declares no side effects.
Emitting an event is a side effect, so event-only functions are writes too.

An unusually large registered human read over 28,000 UTF-8 bytes refuses with
`read_output_limit_exceeded` before printing any partial answer. Its hint names
the field, filter, limit and paging flags that command really has; narrow with
those, or add `--full` to print the complete human reply. This safety
net does not apply to writes, JSON or deliberate machine formats: `--json`
is never refused for size.

Every registered read takes `--section HEADING`, which prints only the
Markdown section under that heading: any level, case-insensitive, up to the
next heading at the same level or shallower. When an oversized reply has
headings, the refusal lists them with each section's size and its exact
`--section` command. A heading the reply lacks refuses with
`read_section_missing` and the same outline. `--section` narrows human text
only, so with `--json` it refuses with `read_section_requires_human_output`.
`yoke items get` with a field and `yoke items section get` keep their
own `--section`, which reads inside one stored field or section.

Suggested root/category/command targets of 40/80/120 lines and
2,400/4,800/7,200 characters prompt readability review. Routine replies target
40 lines and 2,400 characters. These targets are advisory; individual command
size tests guard the routine projections.

## Deliberate data and machine formats

```text
yoke items get APP-7 status --json
yoke items get APP-7 body --section "## Acceptance Criteria"
yoke strategy doc get CURRENT-PLAN --project example --section "Live status"
yoke qa plan list --project example --limit 25 --offset 25
```

`--json` always emits the complete response envelope, including `result`.
Default read projections still select summary fields; `--full` requests their
complete detail and also prints full human output. Database line format,
credential helpers, tool protocols and watcher capture streams retain their
explicit machine contracts.

## Agent help and references

Ask `/yoke help` for a general overview or a specific topic. Topic answers give
the applicable complete recipe and its installed deeper home. The generated
[skill reference](../agents/commands.md) stays available as the complete inventory.
[Installed documentation](../index.md) is the navigation root.
Outside an installed project, read [public documentation](https://upyoke.com/docs)
and [this help reference](https://upyoke.com/docs/cli/help).
`yoke <command> --help` works from any directory and describes the installed
CLI's options; public docs describe the current service. A project-relative
`.yoke/docs` path applies only after that project's operating layer is installed.
