# Worktree lanes, path claims, and scoping

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Lanes and claims
<!-- /yoke:breadcrumbs -->

## Worktree discipline

- Never use `--no-worktree` unless the user asks. Never implement on main.
- The work claim authorizes each lane; launcher `cd` and level labels grant nothing.
  Stage changes follow the [worker rule](../levels.md#stage-level-handoff).
- Prepare the registered lane after claim, read and survey, before edits.
- `upstream-unverified` and `upstream-stale` refusals block preparation and preserve local
  commits. Follow their recovery; never reset, rebase or force-update past them.

See [cleanup](../harness-discovery.md).

## Path claims

- With `path_claims=required_per_task`, the task body owns its file list; read
  [task coverage](../../sessions/model/path-claims.md#task-coverage) first.
- File Budget and path claims are independent axes from `workflows.item.get`
  `effective_policies`; the 350-line `file_line_check` limit always holds. Parity applies only
  when both effective axes are enabled. Budget off, claims on: derive claim paths from the
  execution document. Budget on, claims off: register no claim. Both off: neither is required.
- Claimed paths never narrow scope: a required file stays in the item, its File Budget and its
  claim attempt. Overlap never permits omitting files.
- Claims and `item_dependencies` record coordination and blockers. Only the dependent waits (`yoke items dependency list PREFIX-N`).
- Remediations: classify the overlap (independent → `coordination_only`; ordered →
  `--gate-point activation` with directional evidence; ambiguous → escalate); keep
  `state="blocked"` only on the dependent side; wait for the holder to release;
  coordinate with the holder; ask the holder to narrow or cancel; steering override as the
  last resort (`yoke claims path override --help`, routed through `yoke say --steering`).
- The work-claim holder attests from its own skill (`yoke claims path
  coordination-decision-build`, then `yoke items dependency add` with a rationale). Engineer
  and Tester report to their parent. No live holder → `/yoke refine`. Unattested overlap stays
  incompatible.
- On an unmet gate, park with your claim and lane; the blocker's landing notice wakes you.
- Claims cover physical files, so a symlink claim covers its in-repo target too.
- Item-owned claims release at merge; register fresh coverage before rework
  ([ending coverage](../../sessions/model/path-claims.md#ending-coverage-and-reopening-work)).

## Project scoping

One item, one project: where its code lands. Ask if ambiguous. Code changes in another project
need a linked companion item there; one session may run both lanes. A lane lives in its item's
project checkout. The release-time [consumer proof](../../verification/consumer-proof.md) gate
owns consumer compatibility; a producer-only green run proves only the producer.

## Session scope

A session's project is fixed by its starting folder. It may claim items in any project it can
access; the lane still lives in the item's project checkout.

## Lifecycle and routing

Each item pins `workflow_id` / `workflow_version_id`. Read `yoke workflows item get PREFIX-N`,
then `yoke workflows version get WORKFLOW VERSION`; the binding whose half-open interval holds
the live stage selects `/yoke <skill_id>`. `through_stage_id` is a fresh handoff; never invent
a stage. Lane shape comes from `policies.worktrees` and `policies.generated_children`, not from
a workflow-id branch. Before stating what a harness can do, read
`.yoke/harness/<harness-dir>/manifest.json` (`claude-code` → `claude`).

## Destructive operation discipline

- Never run `git reset --hard`, `git checkout --`/`-f`, `git restore --worktree`,
  `git clean -f*`, `git stash drop`/`clear`, or `rm` on files that are not Yoke-managed
  without user authority.
- Stash or commit first, or use `git reset --soft` / `git restore --staged`. Leave stash drops
  to the operator. Lint tokens here are audit-only.
- `git stash push -u -m "reason" -- <paths>`: the message goes before `--`.
