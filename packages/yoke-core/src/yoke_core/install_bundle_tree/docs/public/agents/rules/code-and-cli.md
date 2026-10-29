# Code conventions and the agent CLI surface

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Code and teaching
<!-- /yoke:breadcrumbs -->

Function ids: [function families](../../functions/index.md).

## Code

- Resolve commits with `git -C <checkout> rev-parse HEAD` and verify with
  `git -C <checkout> cat-file -e '<sha>^{commit}'`. Never invent or expand one.
- `item_id` is the integer `items.id`, not the ref's number (`items.project_sequence`).
- Yoke operations are registered functions: teach the function id and use the `yoke` adapter.
- Stateful helpers and hooks use Python; run hooks via `yoke hook evaluate`.
- Each repeated value has one owner: `~/.yoke/config.json`, DB capability settings or one
  Python constant. Converge stored documents with each contract change.
- Migrations are permanent history; read [databases](databases.md) before schema work.
- Remove retired names from tracked content in the same commit. History stays in commits;
  lasting reasons belong in `docs/archive/decisions/` (`HC-historical-yok-n-cruft`).
- Simulate with real values before acting; verify effects afterward.
- A command that waits silently by design first announces it through `announce_designed_wait`.
- Validate shell-classifier changes against full historical calls, not hand-picked samples.

## Names

Name paths, symbols, tests and prose for their current purpose, for repository readers.
No item refs (`PREFIX-1234`),
plan, milestone, phase, stage, tier, slice, track, wave, batch or feedback provenance, and
no criterion, requirement or spec ids (`AC-7`, `FR-3`, §7), except
runtime data and fixtures (`HC-acceptance-criterion-provenance`). Directory names explain purpose.

## Verify before asserting

Verify identifiers with `rg`, a file, packet or `yoke db read` before naming them.
For live state, cite a registered result, refusal, `--help` or manifest; code alone cannot
prove serving behavior.

## Portable work

- Finish the item, including newly required files. Name blocker owners and recovery.
- Build the smallest working path first; retire old paths and callers in the same change.
- Support local, self-hosted and hosted installs across supported
  environments, databases and tenants. Keep internal concerns out of external projects.
  Read project settings; never branch on one installation. Harness behavior goes behind the
  harness-neutral owner; read each manifest first ([harness discovery](../harness-discovery.md)).
- Consumer edits need a [companion item](lanes-and-claims.md#project-scoping).
  [Consumer proof](../../verification/consumer-proof.md) gates the exact release pair;
  item merges need no consumer build.
- Keep required state with its durable owner. Code must not depend on event presence,
  retention or delivery. Diagnostics may read disposable events; missing telemetry proves nothing.
- Update owning behavior teaching; teach elsewhere only where useful. Follow the
  [teaching standard](../../documentation/index.md). Before extracting private guidance, read
  [execution instructions](../../projects/execution-instructions.md).

## DB authority

The DB is authoritative; `.yoke/BOARD.md` and `.yoke/strategy/` are generated views
([item writes](item-writes.md)). Strategy docs: `yoke strategy --help`. Raw SQL is diagnostic:
`yoke db read "SELECT ..."`, with `<>`. Never build a DB path or DSN. Row repair:
[operator data repair](../../databases/operator-data-repair.md).

## Simplify

Idea, Refine, Conduct, Shepherd and Polish apply:

- Reuse: name the surface you extend, or show your search found none.
- Quality: smallest complete diff; remove redundant state, wrappers and WHAT comments.
- Use modular components with separate concerns and the simplest complete, durable design.
  Avoid speculative abstractions, configuration, indirection and temporary stopgaps.
- Prefer maintained libraries that simplify or improve reliability. Check dependency docs
  and types before implementing.
- Efficiency: cheapest useful path; justify each new table, event, command or setting.

## Related

- [Shell calls and CLI authority](shell-and-cli.md)
