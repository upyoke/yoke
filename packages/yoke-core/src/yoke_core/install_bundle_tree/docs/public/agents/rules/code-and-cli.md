# Code conventions and the agent CLI surface

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Code and teaching
<!-- /yoke:breadcrumbs -->

Function ids: [function families](../../functions/index.md).

## Code

- Resolve a full commit hash with `git -C <checkout> rev-parse HEAD` and check it with
  `git -C <checkout> cat-file -e '<sha>^{commit}'`. Never invent or expand one.
- `item_id` is the integer `items.id`, not the ref's number (`items.project_sequence`).
- Yoke operations are registered functions: teach the function id and use the `yoke` adapter.
- Write stateful helpers and hooks in Python, not shell; hooks run via `yoke hook evaluate`.
- One repeated value has one owner: `~/.yoke/config.json`, DB capability settings or one
  Python constant. A contract change converges stored documents in the same change.
- Migrations are permanent history; read [databases](databases.md) before schema work.
- Remove a retired name from tracked content in the commit that retires it. History goes in
  commits; a lasting reason goes in `docs/archive/decisions/` (`HC-historical-yok-n-cruft`).
- Simulate a change with real values before you run it; verify the effect afterward.
- A command that waits silently by design first announces it through `announce_designed_wait`.
- When you change how shell commands are classified, compare the result against full
  historical calls, not hand-picked samples.

## Names

Codebase-reader naming: name FILE and DIRECTORY names, symbols, tests and prose for what they
do now, for a reader who has only the repository. No epic or work-item refs (`PREFIX-1234`),
plan, milestone, phase, stage, tier, slice, track, wave, batch or field-note provenance, and
no acceptance criterion, functional requirement or spec ids (`AC-7`, `FR-3`, §7), except
runtime data and fixtures (`HC-acceptance-criterion-provenance`). A directory name explains
its purpose.

## Verify before asserting

Check an identifier with `rg`, a file read, a packet or `yoke db read` before you name it.
For live state, cite the registered result, refusal, `--help` or manifest; a code read does not
prove what the serving control plane does.

## Complete and portable work

- Finish the stored scope in this item; a newly found required file stays in scope. Report a
  real blocker with its owner and recovery.
- Build the smallest working path first. Retire the old path and its callers in the same change.
- Shared behavior must work in local, self-hosted and hosted installs. Read project settings;
  never branch on one installation. Harness behavior goes behind the harness-neutral owner;
  read each manifest first ([harness discovery](../harness-discovery.md)).
- Consumer changes need a companion item ([project scoping](lanes-and-claims.md#project-scoping)).
  The release-time exact-pair gate ([consumer proof](../../verification/consumer-proof.md))
  owns consumer compatibility; item merges need no consumer build.
- Required state lives in its durable owner; events are disposable.
- Update the surface that owns changed behavior; teach elsewhere only where it helps. Follow
  the [teaching standard](../../documentation/index.md). Before moving guidance out of a
  private source, read [execution instructions](../../projects/execution-instructions.md).

## DB authority

The DB is authoritative; `.yoke/BOARD.md` and `.yoke/strategy/` are generated views
([item writes](item-writes.md)). Strategy docs: `yoke strategy --help`. Raw SQL is diagnostic:
`yoke db read "SELECT ..."`, with `<>`. Never build a DB path or DSN. Row repair:
[operator data repair](../../databases/operator-data-repair.md).

## Simplify

Idea, Refine, Conduct, Shepherd and Polish apply each axis:

- Reuse: name the existing surface you extend, or state that none exists and how you searched.
- Quality: the smallest complete diff; remove redundant state, wrappers and WHAT comments.
- Efficiency: the cheapest useful path; justify each new table, event, command or setting.

## Related

- [Shell calls and CLI authority](shell-and-cli.md)
