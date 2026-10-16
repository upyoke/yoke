# Terminal help and replies

```text
yoke --help
yoke items --help
yoke items get --help
yoke items get APP-7 status title
```

Yoke plans, builds, verifies and delivers software with people and agents.
Root help lists immediate categories and actions, including `dash` and `task`.
Category help lists immediate children once. Command help owns its supported
recipe, arguments, options and prerequisites. Reading help performs no work.
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

Large human replies save the complete already-redacted envelope and both
rendered output streams to a private temporary JSON file. The reply names its
exact path and says what it holds. Open that file to read the result without
repeating the operation. Workflow entry instructions, successor handoffs,
warnings and refusal recovery remain immediate. If those essentials cannot
fit, `essential_output_limit_exceeded` refuses continuation and points to the
complete saved evidence. Restore writable temporary storage if
`response_evidence_unavailable` prevents saving. Inspect the operation's result
through its read command before retrying a mutation.

Displayed human output has a hard maximum of 350 lines after wrapping at 80
columns, across stdout and stderr. Suggested root/category/command targets of
40/80/120 lines and 2,400/4,800/7,200 characters prompt readability review.
Routine replies target 40 lines and 2,400 characters. These targets are advisory.

## Deliberate data and machine formats

```text
yoke items get APP-7 status --json
yoke items get APP-7 body --section "## Acceptance Criteria"
yoke qa plan list --project example --limit 25 --offset 25
```

`--json` preserves the response envelope. Registered reads retain their
28,000-byte limit. The named refusal teaches a narrower read or explicit
`--full`. `--full` requests complete structured data. Human output still uses
complete saved evidence when it exceeds the display ceiling. Database line
format, credential helpers, tool protocols and watcher capture streams keep
their explicit machine contracts.

## Agent help and references

Ask `/yoke help` for a general overview or a specific topic. Topic answers give
the applicable complete recipe and its installed deeper home. The generated
[skill reference](../agents/commands.md) stays available as the complete inventory.
[Installed documentation](../index.md) is the navigation root.
Outside an installed project, read [public documentation](https://upyoke.com/docs)
and [this help reference](https://upyoke.com/docs/reference/cli-help).
`yoke <command> --help` works from any directory and describes the installed
CLI's options; public docs describe the current service. A project-relative
`.yoke/docs` path applies only after that project's operating layer is installed.
