# YOK-1246 Proof Snapshot

Last updated: 2026-04-10

This file captures the historical closeout proof for the `YOK-1246` /
`YOK-1322` merge wave on `main`. Both items are now done. The remaining notes
here record what landed, what was proven live, and which cleanup seams were
explicitly carried forward into the zero-shell continuation.

## Current Cleanup Ledger

This section is the cold-start handoff for the ongoing closeout work. It tracks
what has already been purged, what was intentionally kept, and what the next
cleanup tranche should target.

`1246-proof.md` has not been archived away elsewhere. It remains on `main` as a
live historical proof ledger for the `YOK-1246` / `YOK-1322` wave and the
zero-shell follow-on waves that came after it.

### Integration Snapshot (2026-04-10)

The `YOK-1246` / `YOK-1322` merge wave is complete on `main`, and the first
grouped post-merge zero-shell continuation wave is also complete on `main`.

Historically landed during the `YOK-1246` integration wave:

- `YOK-1323` body-write / render cutover
- `YOK-1220` done-transition / usher recovery and evidence-only guidance
- `YOK-1324` doctor launcher hardening for worktree imports and failure diagnostics
- `YOK-1255` destructive `yoke.db` mutation guardrails
- `YOK-1326` remaining `sync-helper.sh` GitHub item helpers
- `YOK-1327` public `sync-to-github.sh` create/link orchestration
- `YOK-1328` `update-status.sh` semantic cutover
- `YOK-1329` `done-transition.sh` semantic cutover
- `YOK-1330` `test-update-status.sh` split into pytest + shell smoke
- `YOK-1331` `test-merge-worktree.sh` split into pytest + shell smoke
- `YOK-1251` `populate-registry` / event-catalog / doctor-drift cluster
- `YOK-1279` remaining `sync-helper.sh` / `sync-to-github.sh` write tail
- `YOK-1337` `merge-worktree.sh` core orchestration cutover
- `YOK-1338` worktree lifecycle utility cutover
- `YOK-1339` board helper shell cutover
- `YOK-1340` browser utility shell cutover
- `YOK-1341` hook/session utility cutover
- `YOK-1342` Codex/bootstrap adapter shell cutover
- `YOK-1333` core `yoke-db.sh` dispatcher and primary DB wrappers
- `YOK-1334` secondary DB wrappers and backup flows
- `YOK-1344` project/template ops shell cutover
- `YOK-1335` browser-QA orchestration cluster
- `YOK-1336` deploy-pipeline orchestration cluster

Additional post-merge zero-shell slices already landed directly on `main`:

- `YOK-1279` GitHub sync shell closeout proof refresh
- `YOK-1332` backlog shell cutover
- `YOK-1334` secondary DB wrapper shell cutover
- `YOK-1337` merge utility shell cutover
- `YOK-1338` worktree lifecycle/path cutover
- `YOK-1339` board/render helper cutover
- `YOK-1341` session/hook helper cutover
- `YOK-1344` project/bootstrap/helper cutover

The corresponding local worktrees for those eight slices were absorbed and then
deleted after ancestry verification against `main`.

The grouped residual branch `zero-shell-wave-1` also landed on `main` as:

- `YOK-1213` `lint-sqlite-cmd.sh`
- `YOK-1265` shared-core utility tranche
- `YOK-1346` `lint-event-registry.sh`
- `YOK-1347` `validate-buzz-pipeline.sh`
- `YOK-1348` `lock-helper.sh`
- `YOK-1349` `bootstrap-project.sh`

The shared branch and its worker worktrees were then deleted locally after
ancestry verification against `main`.

### Zero-Shell Wave 2 Shared-Branch Snapshot (2026-04-10)

`zero-shell-wave-2` now carries the Wave 2 worker lanes (`YOK-1351` through
`YOK-1360`) plus the integrator-owned `YOK-1361` glue needed to make the
shared branch truthful before the final simulate / merge handoff.

What landed on the shared branch during the integration pass:

- `yoke-db.sh` now delegates the `sections` family to
  `runtime.api.domain.sections` and the raw SQL escape hatch to
  `runtime.api.cli.raw_query`, with `lint_sqlite_cmd.py` updated to treat the
  Python raw-query path as the same guarded escape hatch.
- `sections.py` keeps copied-shell smoke semantics intact by honoring the
  caller-relative `render-body.sh` override path, so stale-body protection
  remains green even after the shell extraction.
- Lane I is wired through `runtime.api.cli.shim_launcher` /
  `shim_registry.py`, but the integration reality is a tiny bootstrap wrapper
  per compatibility shim, not a literal one-line shell. That wrapper preserves
  copied-shim target-root resolution and `YOKE_SCRIPTS_DIR` semantics while
  moving the behavior behind `yoke.api`.
- `repair-status.sh` intentionally stayed on its dedicated thin launcher
  instead of the shared shim path, and the Python engine now normalizes
  repo-root-style `YOKE_ROOT` values plus injects the sanctioned
  `YOKE_CLAIM_BYPASS` / done nonce context that the emergency repair path
  needs.
- `populate-registry.sh` and `test-populate-registry.sh` are now deleted.
  The canonical regeneration path is `python3 -m runtime.api.domain.populate_registry`,
  and the surrounding doctor / event-contract / README / migration docs were
  refreshed to match.
- `yoke/docs/shell-inventory.md` and `yoke/docs/scripts.md` were refreshed
  so the surviving shell floor is described as it actually exists on the shared
  branch, not as the pre-integration plan imagined it.

Shared-branch verification completed:

- `python3 -m pytest yoke/api/`
  Result: `5070 passed`
- Shell smoke manifest:
  `test-body-sync.sh`, `test-lifecycle-mutation-guard.sh`,
  `test-stale-body-guard.sh`, `test-repair-status.sh`,
  `test-doctor-launcher.sh`, `test-resolve-item-worktree.sh`,
  `test-query-items.sh`, `test-query-items-project.sh`,
  `test-update-status.sh`, `test-backup-db.sh`, `test-project-db.sh`,
  `test-write-to-main.sh`, `test-check-ac-presence.sh`,
  `test-check-hard-blocks.sh`, `test-classify-browser-qa.sh`,
  `test-designs-db.sh`, `test-env-db.sh`, `test-flow-db.sh`,
  `test-github-actions.sh`, `test-install-worktree-deps.sh`,
  `test-normalize-ac-labels.sh`, `test-ouroboros-db.sh`,
  `test-release-notes-db.sh`
  Result: all passed

What remains before calling the wave done:

- Run the final full-harness integration simulation (`/yoke simulate` or the
  equivalent supported harness path) from `zero-shell-wave-2`.
- Merge `zero-shell-wave-2` to `main`, then do the normal branch/worktree
  ancestry cleanup.

### Post-Merge Next-Wave Plan

`YOK-1246` and `YOK-1322` are done on `main`, and the first grouped residual
wave is done too. The remaining real migration queue is now only three shell
utility files / `313` shell lines:

- `classify-dirty-files.sh`
- `lock-helper.sh`
- `status-lifecycle.sh`

Those residual files need fresh follow-on tickets. Do not reuse the closed
ticket IDs from the waves that already landed.

#### Rules For Safe Parallelism This Time

- One issue = one worktree.
- Each issue body must list its exact owned shell files.
- No opportunistic edits outside the owned file set.
- No worker lane touches proof, inventory, or backlog planning docs.
- If unavoidable glue is needed across lanes, wire it later on the shared
  integration branch instead of expanding worker scope.

#### Integrator-Owned Shared Files

Keep these as integrator-owned unless a lane absolutely must touch them:

- `yoke/docs/1246-proof.md`
- `yoke/docs/shell-inventory.md`
- `yoke/docs/scripts.md`
- `CLAUDE.md`

The point is to let the code lanes land on narrow write scopes and reconcile
shared documentation only at merge-back time.

#### Residual File Map

The ownership table in `shell-inventory.md` is still the master file map, but
the three remaining migrate-to-Python rows should be treated as residual
reticketing work now rather than as belonging to the closed tickets that got us
here.

#### Queued Event-Ledger Follow-Ons

- `YOK-1254`
- `YOK-1272`
- `YOK-1286`
- `YOK-1288`

#### Endgame Lanes, Not Part Of The Active Shell Wave

- `YOK-1189`
- `YOK-1300`

### Reading The Remaining Shell Estate Honestly

The raw shell-file count overstates the permanent shell footprint.

- `shell-inventory.md` currently shows `334` shell files.
- `180` shell tests / `62,893` lines are contingent coverage, not permanent
  shell residents.
- `41` shell files are now explicitly classified as vendored, template, or
  emitted external artifacts rather than repo-internal migration debt.
- `3` files / `313` shell lines are the real remaining Python migration queue.
- The real logic migration queue is now much smaller than the raw shell count
  suggests because many merged surfaces are already Python-owned and retained
  only as compatibility shims or justified runtime boundaries.
- The steady-state shell floor is still the runtime boundary set plus whatever
  smoke coverage still earns its place after the remaining migrations land.

### Canonical DB Leak Recovery (2026-04-09)

- Worktrees still share the canonical `yoke/yoke.db` unless a test or temp
  fixture repo sets an isolated `YOKE_ROOT`. That design is intentional, but
  it means any lost test isolation mutates live Yoke state immediately.
- The visible `YOK-1` regression on `BOARD.md` came from a live probe command
  in the real repo:
  `YOKE_CLAIM_BYPASS=test ... backlog-registry.sh update 1 status implementing`
  with no isolated `YOKE_ROOT`.
- Retained DB backups in both `yoke/backups/` and the home directory proved
  the latest status flip was accidental, but all retained snapshots were
  already carrying the poisoned `YOK-1` body from `2026-03-17`.
- The original `YOK-1` body was recovered from Git history
  (`fcab9ffd81bd33b38f7aa11e5f596e9e40021bbb^:yoke/backlog/001.md`) and
  restored through the sanctioned backlog mutation path.
- `YOK-1` status was repaired back to `done`, and GitHub issue `#37` plus the
  generated board are now back in sync with that corrected live state.
- Root fix now landed in code on both `main` and `YOK-1246`:
  - `backlog-registry.sh` refuses `YOKE_CLAIM_BYPASS=test` writes against the
    canonical DB unless an explicit isolated `YOKE_ROOT` is set
  - board rebuild follows the actual target repo root instead of always using
    the operator checkout
  - new regression `test-backlog-registry-isolation.sh` covers both behaviors
- Follow-on hardening also landed immediately:
  `repair-status.sh` / `runtime.api.engines.repair_status` now inject the
  one-shot done nonce automatically, so emergency `status=done` repairs no
  longer require a manual operator workaround.

### Completed In This Closeout Wave

- Deleted the retired shell compatibility DB wrappers and rewired live callers
  to `yoke-db.sh` (`epic`, `events`, `runs`, `qa`).
- Deleted completed migration cargo that no longer serves live behavior:
  - obsolete migration scripts
  - obsolete migration tests
  - stale wrapper references
  - stale pre-`reviewed-implementation` / passed-era wording in active prompts and docs
- Converted `observe-tool.sh` into a thin launcher and moved the remaining
  attribution/session fallback logic into Python.
- Removed pure stale shell suites that only preserved retired lifecycle
  behavior or replaced Python-owned board coverage:
  - `test-passed-auto-usher.sh`
  - `test-done-transition-passed.sh`
  - `test-board-lifecycle.sh`
  - `test-board-age-type-badges.sh`
  - `test-sun532-task-status-mapping.sh`
- Modernized still-live shell suites off retired lifecycle terms:
  - `test-items-progress.sh`
  - `test-epic-simulation-gate.sh`
  - `test-done-transition-sim-gate.sh`
  - `test-qa-tables.sh` (stale migration block removed, current schema checks kept)
- Fixed two pre-existing red suites that surfaced during cleanup instead of
  masking them:
  - restored shell-owned epic-format validation ordering in
    `backlog-registry.sh` so `cmd_add` rejects malformed `epic` values before
    the Python create adapter parses them
  - aligned `HC-missing-flow` with the documented/backfill rules by excluding
    `wontdo` items and epic-child rows while still warning on real missing-flow
    parent items, including `idea` items
- Hardened another thin launcher seam instead of leaving test-only drift in
  place:
  - `service-client.sh` now resolves the real Python repo root via
    `REAL_SCRIPTS`, matching the newer launcher pattern already used by
    `doctor.sh` and `yoke-db.sh`
- Standardized the live QA gate vocabulary off retired lifecycle labels:
  - runtime contracts now use `implementation_review` and `verification`
    instead of `review` / `validation`
  - both the Python and shell QA schema initializers migrate legacy rows
    forward on `init`, so fresh and upgraded DBs land on the same contract
  - the conduct preflight shell suite was renamed to
    `test-issue-reviewed-implementation-preflight.sh` so the file name matches
    the live checkpoint it covers
- Deleted retired dependency-migration cargo that no longer has a live caller:
  - removed `migrate-depends-on.sh`
  - removed `test-migrate-depends-on.sh`
  - corrected docs that still claimed doctor `--fix` delegated to that script
- Tightened the backlog bootstrap migrator to the live lifecycle contract:
  - `migrate-to-sqlite.sh` no longer accepts retired item statuses as valid
    round-trip values
  - `test-migrate-to-sqlite.sh` now seeds canonical lifecycle statuses and
    proves the stricter bootstrap contract end-to-end
- Cleaned the adjacent backlog-view shell suites so they no longer preserve
  retired status fixtures:
  - `test-generate-backlog-md.sh` now seeds `implementing` instead of `active`
    for the non-done backlog item it regenerates
  - `test-classify-dirty-files.sh` now uses canonical backlog fixture statuses
    (`implementing`, `reviewed-implementation`) in its frontmatter-only dirty
    file scenarios
- Cleaned another pair of runtime-adjacent shell suites off retired lifecycle
  wording:
  - `test-flow-db.sh` now seeds `implementing` for the `item_progress_view`
    fixture instead of retired `active`
  - `test-on-agent-stop.sh` now expects the live
    `before reviewed-implementation` safety-net message and seeds
    `implementing` epic-task fixtures in its session-ID coverage
- Rewrote the feed reconcile shell matrix to the canonical dependency contract:
  - dependent items now seed `planned` instead of retired `ready`
  - blocker items now seed `implementing` instead of retired `active`
  - the `validation_before_start` case now uses the live
    `status:implemented` satisfaction instead of invalid `status:passed`
- Cleaned the next browser/planning shell residue tranche without weakening the
  behavior under test:
  - `test-browser-run-scenario.sh` now seeds the non-primary browser QA items as
    `reviewing-implementation` instead of retired `validate`, matching the
    live QA-stage fixture already used elsewhere in the suite
  - `test-dependency-planning.sh` now proves the same activation and
    integration gate semantics using canonical lifecycle fixtures
    (`planned` / `implementing` / `implemented`) instead of retired
    `ready` / `active` / `review`
- Cleaned the next frontmatter/body/deploy shell residue tranche and fixed the
  stale expectations it exposed:
  - `test-untracked-views.sh` now regenerates backlog frontmatter with the
    canonical `implementing` status, and its deleted `pre-conduct-sweep.sh`
    assertion was replaced with the live contract: that legacy bookkeeping
    script is gone
  - `test-stale-body-guard.sh` now seeds canonical `implementing` fixtures and
    asserts the actual `HC-stale-body` contract: warn only when
    `spec_updated_at > body_generated_at`, not merely when metadata is absent
  - `test-done-transition-deploy-guard.sh` now seeds `implemented` items,
    matching the already-live post-merge entry state used by the other
    done-transition shell suites
- Fixed one live hook regression and cleaned the surrounding operator wording:
  - `on-bash-complete.sh` now syncs progress notes for `implementing` epic
    tasks instead of branching on retired `active`
  - `test-on-bash-complete-root.sh` now guards that hook behavior directly so
    the stale status check cannot silently return
  - nearby operator/help surfaces were aligned with the same contract
    (`before implementing`, delivery-tail wording, current blocker examples,
    and the `doctor.sh` status-consistency description)
- Cleaned another small shell-test residue tail in labels/history coverage:
  - `test-body-sync.sh` now mocks GitHub status labels with
    `status:implementing` instead of retired `status:active`
  - `test-yoke-db.sh` now records epic task history as
    `pending -> implementing` instead of `pending -> active`
  - `test-sync-task-label.sh` comments/assertions now describe the live
    `status:implementing` label sync contract
- Cleaned another doc-only residue pass that still taught the retired delivery
  path in examples and command tables:
  - `test-inventory.md` now uses `implementing` /
    `reviewing-implementation` / `release` in its stage map
  - `harness-adapter-template.md` and `harness-bootstrap.md` now describe
    `shepherd` as driving work to `planned`, not `ready`
  - `state-management.md` now names the `reviewed-implementation` checkpoint as
    implementation review completion rather than “review passed”
- Cleared another residue tranche of stale shell fixtures:
  - done-transition shell suites now seed the canonical post-merge
    `implemented` status instead of retired `active`
  - sync-to-github shell suites now use the current `items` schema and the
    canonical epic-task `planned` status instead of retired `ready`
  - merged-at shell coverage now bypasses newer claim/task guards explicitly so
    it tests the merged-at contract rather than unrelated enforcement layers
  - board/query shell coverage has started moving from retired `active` fixtures
    to canonical issue lifecycle values, and the obsolete board widget shell
    suite was deleted instead of patched back around vanished shell functions
- Repaired three more pre-existing red shell suites by updating them to the
  current mutation/claim contract instead of preserving retired lifecycle
  assumptions:
  - `test-item-status-events.sh` now emits `ItemStatusChanged` across canonical
    issue statuses (`idea -> implementing -> blocked`) with claim bypass
  - `test-done-nonce-gate.sh` now seeds current `implemented` issue fixtures and
    verifies the nonce gate independently from the newer claim guard
- Fixed another stale-but-live shell suite that had drifted behind the current
  `items` schema and GH sync behavior:
  - `test-frozen-label-sync.sh` now inserts current-schema fixtures directly,
    uses canonical issue status values, and matches the actual `gh label create`
    / `gh issue edit --add-label|--remove-label` calls
- Rewrote the board unknown-status shell suite to match the real post-purge
  contract:
  - canonical issue/epic statuses classify without an `Unknown` section
  - retired shared statuses (`defined/designed/ready/active/review/validate/passed`)
    are now explicitly expected to route to `Unknown`
- Cleaned the remaining high-value lifecycle residue out of the two largest
  still-live shell regression suites:
  - `test-update-status.sh` now seeds canonical epic-task and parent-item
    statuses (`planned` / `implementing`) instead of retired `ready` /
    `active`, its stale function names are gone, and the mixed-task
    auto-derive case now asserts the real live contract (`planned` parent ->
    `implementing` once work is in flight)
  - `test-merge-worktree.sh` now uses canonical backlog and epic-task fixture
    statuses (`planned` / `implementing`) instead of retired `ready` /
    `active`, including the backlog-conflict fixture and helper DB schemas
- Cleaned the done-transition seam so it reads like the current lifecycle
  instead of the migration path:
  - `done-transition.sh` no longer tells operators to enter evidence-only
    items as `active`, and its inline status comments no longer narrate
    retired `active` / `passed` history
  - `test-done-transition-gaps.sh` now describes the live cascade contract
    (`implementing` / `release` / `done`) instead of stale
    `completed` / `ready` / `active` terminology
- Fixed a pre-existing red schema regression suite by aligning it with the
  actual zero-legacy DB contract instead of the retired compatibility layer:
  - `test-schema-extensions.sh` now treats `epic_task_history`,
    `epic_simulations`, `sprints`, and `tracks` as intentionally absent on
    fresh init, while still proving the current shared tables, epic-task
    migration, and implementation-family CHECK constraints
  - the old-schema preservation fixture in that suite now seeds canonical
    `planned` task statuses instead of retired `ready`
- Fixed the deployment pipeline shell suite by aligning it with the already-live
  deployment contract instead of stale `passed` fixtures:
  - `test-deploy-pipeline.sh` now seeds member items as `implemented`, which
    matches `deploy-pipeline.sh`'s canonical `implemented -> release`
    transition path
  - this removed five pre-existing failures where the suite still expected
    `passed -> release` despite the production script having already cut over
- Deleted another completed schema-migration remnant instead of preserving it
  as archaeology:
  - removed the dead `drop-epic-passed-trigger` subcommand from `schema-db.sh`
  - rewrote the fresh-init schema comment so it describes current runtime
    status derivation rather than the retired `passed`-era trigger history
  - updated `test-schema-db.sh` header wording so it describes the surviving
    historical epic-task migration contract instead of generic “legacy status
    normalization”
- Renamed one remaining live shepherd phase path to match the current
  lifecycle contract:
  - the shepherd planning gate now lives at `planning-to-planned-gates.md`
  - updated the shepherd skill and command/script docs so the phase name
    matches the current `planned` transition it gates
- Renamed the advance implementation sub-skill off retired `active`
  terminology:
  - the implementation kickoff subtree now lives under
    `advance/implementing/`
  - updated the advance skills, doctor prompt-surface glob, browser-QA shell
    test, live docs, and archive references so the path and prose now describe
    the current `implementing` handoff directly
- Deleted one dead incident-recovery shell utility instead of carrying it as
  permanent shell baggage:
  - removed `recover-epic-tasks.sh`, a YOK-926 one-off repair script with no
    live callers outside its own doc entry
  - removed the stale `scripts.md` entry for that deleted recovery path
- Fixed a real worktree-launch regression that showed up while updating the
  backlog through `YOK-1246` scripts from the main checkout:
  - several thin launchers were exporting `PYTHONPATH` correctly but still
    running from the caller's CWD, which let the `main` checkout shadow the
    `YOK-1246` package when both repos existed on disk
  - the launcher family now `cd`s into the resolved worktree root before
    `python3 -m ...`, and a regression shell test proves that
    `sync-helper.sh` no longer imports the stale `main` package in that
    shadowed-CWD scenario
- Fixed the separate `create-worktree.sh` leak that produced a real stray
  `YOK-42` worktree during shell smoke coverage:
  - the thin launcher now separates code-root imports from target-repo
    mutation, passing the real operation root explicitly instead of mutating
    whichever checkout happened to own the Python package
  - both `main` and `YOK-1246` now have a real-launcher regression test that
    proves a temp smoke repo creates `.worktrees/YOK-42` under the temp repo,
    not under `/Users/dev/yoke/.worktrees`
  - the leaked local `YOK-42` worktree and branch were deleted after verifying
    that their tip was already reachable from `main`
- Cleaned one more small live terminology tranche:
  - `browser-qa-scenarios.md` now requires browser QA requirements before an
    item enters `implementing`, not a retired lifecycle state
  - `hook-helpers.sh` now describes the current pre-`implementing` attribution
    window
  - `advance/SKILL.md` now explains the single-worktree review-loop behavior
    directly instead of narrating the retired status era
- Corrected two stale doctor checks to the current lifecycle contract:
  - `HC-orphaned-active-items` no longer treats legacy `ready` rows as live
    in-flight worktree states
  - `HC-run-item-status-consistency` now warns on `implemented` items left in
    executing deployment runs instead of looking for the retired `passed`
    state
- Folded the body/render and epic-link cleanup fully into this branch:
  - merged `YOK-1323`, making renderer-owned `items.body` and removing the raw
    body-write path from `backlog-registry.sh`
  - purged the retired parent-epic item field from runtime code, tests, and docs;
    the only intentional remaining reference is the merge-adjacent
    `schema-db.sh migrate-drop-items-epic` path
- Folded the next two GitHub-sync lanes into this branch:
  - `YOK-1326` moved the remaining `sync-helper.sh` item-helper behavior behind
    Python ownership while keeping the sourced shell contract intact
  - `YOK-1327` moved the public `sync-to-github.sh` entrypoint to a thin
    launcher while preserving the newer ID-based epic semantics already living
    in Python
- Folded `YOK-1328` into this branch:
  - `update-status.sh` is now a 24-line launcher into
    `runtime.api.domain.update_status`
  - the new `yoke/api/test_update_status.py` owns 32 focused Python cases
    for the Python-owned auto-derive / checkbox / repo-resolution behavior
- Folded `YOK-1330` into this branch:
  - `test-update-status.sh` is now a 21-test shell smoke suite focused on CLI
    parsing, portability, and `HC-comment-sync`
  - `yoke/api/test_update_status_full.py` now owns 26 migrated subprocess
    behavioral cases that used to live in the shell harness
  - together with the existing 32 fast unit-style Python cases, the
    post-split `update-status` coverage now passes as `21 shell smoke + 58
    pytest`
- Folded `YOK-1331` into this branch:
  - `test-merge-worktree.sh` is now a 16-test shell smoke suite focused on the
    shell-native CLI / git / worktree boundary
  - `yoke/api/test_merge_worktree_full.py` now owns 56 migrated subprocess
    behavioral cases that used to live in the shell harness
  - the split makes ownership much clearer, but it does **not** fix the timing
    problem on this surface yet
- Folded `YOK-1329` into this branch:
  - `done-transition.sh` is now a 78-line launcher into
    `runtime.api.engines.done_transition`
  - the Python engine now follows the live `YOK-1246` schema and uses the
    item's own numeric ID for epic-task cascade semantics instead of the
    retired parent-epic item field
  - stale-cleanup, retry-exhaustion, legacy-branch guidance, and branch-fix
    behavior are now verified through the Python-owned implementation
- Kept the shell inventory current after each shell-file change. Current
  generated snapshot: `314` shell files total, `182` shell tests, and `3`
  remaining control-plane write-orchestration files.

### Verified Replacements

- Python board ownership is green after deleting the old shell board suites:
  - `python3 -m pytest yoke/api/board/tests/test_sections.py -q` ->
    `71 passed`
  - `python3 -m pytest yoke/api/board/tests/test_renderer.py -q` ->
    `35 passed`
- Modernized shell suites are green:
  - `test-items-progress.sh` -> `17/17 passed`
  - `test-epic-simulation-gate.sh` -> `13/13 passed`
  - `test-done-transition-sim-gate.sh` -> `28/28 passed`
  - `test-qa-tables.sh` -> `50/50 passed`
  - `test-qa-gate-check.sh` -> `29/29 passed`
  - `test-issue-reviewed-implementation-preflight.sh` -> `24/24 passed`
  - `test-migrate-to-sqlite.sh` -> `97/97 passed`
  - `test-generate-backlog-md.sh` -> `12/12 passed`
  - `test-classify-dirty-files.sh` -> `31/31 passed`
  - `test-flow-db.sh` -> `55/55 passed`
  - `test-on-agent-stop.sh` -> `33/33 passed`
  - `test-feed-reconcile.sh` -> `24/24 passed`
  - `test-browser-run-scenario.sh` -> `42/42 passed`
  - `test-dependency-planning.sh` -> `35/35 passed`
  - `test-untracked-views.sh` -> `17/17 passed`
  - `test-stale-body-guard.sh` -> `29/29 passed`
  - `test-done-transition-deploy-guard.sh` -> `50/50 passed`
- Pre-existing shell failures resolved in this tranche:
  - `test-missing-flow.sh` -> `28/28 passed`
  - `test-done-transition-result-file.sh` -> `30/30 passed`
  - `test-done-transition-retry.sh` -> `16/16 passed`
  - `test-sync-empty-worktree.sh` -> `15/15 passed`
  - `test-sync-to-github-cross-project.sh` -> `6/6 passed`
  - `test-merged-at-population.sh` -> `11/11 passed`
  - `test-item-status-events.sh` -> `15/15 passed`
  - `test-done-nonce-gate.sh` -> `16/16 passed`
  - `test-frozen-label-sync.sh` -> `10/10 passed`
  - `test-board-unknown-status.sh` -> `13/13 passed`
- Largest lifecycle-residue suites reverified after canonical fixture cleanup:
  - `test-update-status.sh` -> `21/21 passed`
  - `test-merge-worktree.sh` -> `16/16 passed`
- Migrated Python coverage for the `update-status` shell split is green:
  - `python3 -m pytest yoke/api/test_update_status.py -q` -> `32 passed`
  - `python3 -m pytest yoke/api/test_update_status_full.py -q` -> `26 passed`
- Migrated Python coverage for the `merge-worktree` shell split is green:
  - `python3 -m pytest yoke/api/test_merge_worktree_full.py -q` -> `56 passed`
- Done-transition lifecycle cleanup is green:
  - `python3 -m pytest yoke/api/engines/test_done_transition.py -q` ->
    `33 passed`
  - `test-done-transition-gaps.sh` -> `54/54 passed`
  - `test-done-transition-retry.sh` -> `16/16 passed`
- Pre-existing schema regression suite is green after contract cleanup:
  - `test-schema-db.sh` -> `62/62 passed`
  - `test-schema-extensions.sh` -> `158/158 passed`
- Deployment pipeline suite is green after canonical lifecycle cleanup:
  - `test-deploy-pipeline.sh` -> `79/79 passed`
- Python coverage around the new `HC-missing-flow` semantics is green:
  - `python3 -m pytest yoke/api/engines/test_doctor_meta.py yoke/api/engines/test_doctor_hc_meta_full.py -q`
    -> `108 passed`
- Advance implementation-surface path cleanup is green:
  - `test-advance-browser-qa.sh` -> `24/24 passed`
  - `python3 -m pytest yoke/api/engines/test_doctor_hc_meta_full.py yoke/api/engines/test_doctor_filesystem_full.py -q`
    -> `125 passed`
- Doctor lifecycle cleanup is green:
  - `python3 -m pytest yoke/api/engines/test_doctor_db.py yoke/api/engines/test_doctor_hc_db_full.py yoke/api/engines/test_doctor_hc_git_full.py -q`
    -> `202 passed`
- Python board widget ownership is green after deleting the obsolete shell
  widget suite:
  - `python3 -m pytest yoke/api/board/tests/test_widgets.py -q` ->
    `52 passed`
- Python QA/epic contract suites are green after the vocabulary cleanup:
  - `python3 -m pytest yoke/api/test_qa.py yoke/api/test_qa_full.py yoke/api/test_epic.py yoke/api/test_epic_full.py yoke/api/test_mutations.py yoke/api/test_service_client.py yoke/api/engines/test_doctor_hc_db_full.py -q`
    -> `656 passed`
- Status-event shell coverage is green after canonical fixture cleanup:
  - `test-events-compat-views.sh` -> `23/23 passed`
  - `test-repair-status-events.sh` -> `19/19 passed`
- Hook/root coverage is green after the `on-bash-complete.sh` lifecycle fix:
  - `test-on-bash-complete-root.sh` -> `10/10 passed`
  - `test-issue-lifecycle.sh` -> `80/80 passed`
- Hook helper cleanup remains green after the latest terminology pass:
  - `test-hook-helpers.sh` -> `27/27 passed`
- Remaining shell-test label/history cleanup is green:
  - `test-body-sync.sh` -> `19/19 passed`
  - `test-yoke-db.sh` -> `91/91 passed`
  - `test-sync-task-label.sh` -> `14/14 passed`

### Next Residue Queue

The explicit shell-test fixture scan for retired item lifecycle statuses is now
clean. What remains to audit next is broader residue, not the already-cleaned
fixture patterns.

Still treat these as intentional and not lifecycle residue by default:
- `event_registry.status = 'active'`
- deployment QA verdict/status values like `passed`
- sprint rows whose own canonical status is still `active`

The next cleanup tranche should prioritize:
- non-test docs and prompt surfaces that still narrate retired lifecycle words
  as if they are current
- completed-migration archaeology in otherwise-live shell/docs surfaces
- any historical repair or compatibility paths that can now be deleted instead
  of maintained

The current focused regex scans no longer return shell-test item fixtures or
label/history assertions that seed retired `active` / `ready` / `review` /
`validate` lifecycle values. The remaining hits are intentional current-state
tokens such as `reviewing-implementation` and non-item environment statuses
like ephemeral env `ready`.

The next likely seam is migration-archeology cleanup plus non-test prompt/doc
residue in shell-owned surfaces. `schema-db.sh` no longer carries the dead
trigger cleanup path, the shepherd planning gate file now matches the current
`planned` transition, and the advance implementation kickoff subtree now lives
under `advance/implementing/`. The remaining candidates are other historical
repair or compatibility branches that still survive inside live shell owners
plus any docs that still describe retired lifecycle wording as present-tense
behavior. The retired `migrate-depends-on.sh` path and its shell test were
deleted from the worktree because doctor no longer shells out to that one-time
migrator, and `test-migrate-to-sqlite.sh` was rewritten to current statuses
instead of preserving pre-cutover `active` fixtures. The neighboring
backlog-view suites (`test-generate-backlog-md.sh`,
`test-classify-dirty-files.sh`) were cleaned in the same wave, followed by
`test-flow-db.sh`, `test-on-agent-stop.sh`, `test-feed-reconcile.sh`,
`test-browser-run-scenario.sh`, `test-dependency-planning.sh`,
`test-untracked-views.sh`, `test-stale-body-guard.sh`,
`test-done-transition-deploy-guard.sh`, `test-events-compat-views.sh`, and
`test-repair-status-events.sh`.

If a shell test only proves already-retired migration behavior, delete it.
If it still covers a live shell boundary, keep the test but rewrite the
fixtures to canonical lifecycle values.

The latest larger cutover landed on `repair-status.sh`. That file no longer
owns parsing, lifecycle validation, ID normalization, or task/item repair
branching in shell; it is now a 59-line launcher into
`runtime.api.engines.repair_status`, with new pytest coverage in
`yoke/api/engines/test_repair_status.py`. The legacy operator-facing command
stayed stable, and the existing shell suite still passes, so this reduced real
shell authority without creating another compatibility shim. The refreshed
inventory now records `316` total shell files, `197` kept as true shell
boundaries, and `119` still queued under `migrate to Python`.

The next high-leverage follow-on landed on `emit-event.sh`. That file also
collapsed to a 59-line launcher, with the real validation, session/project
fallback, registry warning, envelope construction, and insert path now owned
by `runtime.api.domain.emit_event`. The event-platform shell contract still
passes end to end, and the refreshed inventory now records `316` total shell
files, `198` kept as true shell boundaries, and `118` still queued under
`migrate to Python`.

The next adjacent epic-sync slice moved both task GitHub sync helpers into
Python ownership under `runtime.api.domain.epic_task_sync`. Both
`sync-task-label.sh` and `sync-task-body.sh` are now 59-line launchers, and
the live `runtime.api.domain.epic` plus `runtime.api.engines.resync` paths call
the Python owner directly instead of bouncing back out through shell. That
keeps the shell CLI contract intact while deleting another pocket of real
write-side shell authority, and the refreshed inventory still records `316`
total shell files, `198` kept as true shell boundaries, and `118` still
queued under `migrate to Python`.

The follow-on in the same neighborhood moved `sync-progress.sh` under that
same Python owner. `runtime.api.domain.epic_task_sync` now handles epic-task
progress comments, label sync, and body sync; `sync-progress.sh` is down to a
thin launcher; and the old hook/doc wording about changing directories to
rescue shell-relative paths has been removed. The refreshed inventory now
records `316` total shell files, `201` kept as true shell boundaries, and
`115` still queued under `migrate to Python`, with control-plane write
orchestration down to `5` shell files.

The next `sync-to-github.sh` slice moved the public `--backfill-titles` and
`--backfill-labels` entrypoints into that same Python owner. The shell script
now treats those flags as thin shims into `runtime.api.domain.epic_task_sync`,
and `sync-helper.sh` no longer carries the old `backfill_task_titles` or
`backfill_task_labels` implementations. The proof/doc pass also fixed a
pre-existing shell test fixture drift in `test-dedup-github-issues.sh` where
the setup still inserted retired `items.sprint/track/track_seq` columns. The
refreshed inventory still records `316` total shell files, `201` kept as true
shell boundaries, and `115` still queued under `migrate to Python`.

The next adjacent cut moved `sync_frozen_label` into
`runtime.api.domain.backlog_github_sync`. `sync-helper.sh` now keeps only a
thin sourced wrapper for that call surface while the real DB lookup,
project-aware repo routing, and GitHub label mutation live in Python. The
follow-on polish also fixed the frozen-label shell fixture to initialize the
`projects` table, which removed the stale board-render warnings that were
showing up during `backlog-registry.sh update ... frozen ...` coverage. The
refreshed inventory still records `316` total shell files, `201` kept as true
shell boundaries, and `115` still queued under `migrate to Python`.

The next integrated lane was `YOK-1328`. `update-status.sh` no longer owns
argument parsing, epic-task status mutation, auto-derive logic, repo
resolution, or GitHub checkbox handling in shell; it is now a thin launcher
into `runtime.api.domain.update_status`, with dedicated pytest coverage in
`yoke/api/test_update_status.py`. The refreshed inventory now records `314`
total shell files, `198` kept as true shell boundaries, `116` still queued
under `migrate to Python`, and only `4` remaining control-plane
write-orchestration files.

The next integrated lane was `YOK-1330`. The old all-in-one
`test-update-status.sh` shell regression harness is now split along the actual
ownership boundary: a 21-test shell smoke suite for CLI / portability /
doctor-resync integration, plus a new `yoke/api/test_update_status_full.py`
subprocess suite for 26 migrated behavioral cases. Measured together with the
existing fast unit suite, the post-split update-status verification stack is
now faster than the old monolithic shell baseline.

The next integrated lane was `YOK-1331`. The old all-in-one
`test-merge-worktree.sh` shell regression harness is now split into a 16-test
shell smoke suite plus `yoke/api/test_merge_worktree_full.py` with 56
migrated subprocess behavioral cases. That split improved ownership and
maintainability, but the combined runtime is still slower than the branch-point
shell baseline, so `merge-worktree` remains a timing blocker for `YOK-1246`.

## Coverage Snapshot

Goal from `YOK-1246`: every new `yoke/api/domain/` or
`yoke/api/engines/` module should exceed `80%` pytest line coverage.

Measured commands were run from the `YOK-1246` worktree with isolated
`COVERAGE_FILE` outputs so results do not bleed across modules.

| Module | Command | Coverage | Status |
| --- | --- | ---: | --- |
| `runtime.api.domain.observe` | `python3 -m pytest yoke/api/test_observe.py yoke/api/test_observe_full.py --cov=runtime.api.domain.observe -q` | `89%` | meets goal |
| `runtime.api.domain.deployment_runs` | `python3 -m pytest yoke/api/test_deployment_runs.py yoke/api/test_deployment_runs_full.py --cov=runtime.api.domain.deployment_runs -q` | `81%` | meets goal |
| `runtime.api.domain.qa` | `python3 -m pytest yoke/api/test_qa.py yoke/api/test_qa_full.py --cov=runtime.api.domain.qa -q` | `84%` | meets goal |
| `runtime.api.domain.epic` | `python3 -m pytest yoke/api/test_epic.py yoke/api/test_epic_full.py --cov=runtime.api.domain.epic --cov-report=term-missing -q` | `82%` | meets goal |
| `runtime.api.domain.events_crud` | `python3 -m pytest yoke/api/test_events_crud.py yoke/api/test_events_crud_full.py --cov=runtime.api.domain.events_crud -q` | `83%` | meets goal |
| `runtime.api.engines.resync` | `python3 -m pytest yoke/api/engines/test_resync.py yoke/api/engines/test_resync_full.py --cov=runtime.api.engines.resync --cov-report=term-missing -q` | `82%` | meets goal |
| `runtime.api.engines.doctor` | `python3 -m pytest yoke/api/engines/test_doctor_db.py yoke/api/engines/test_doctor_git.py yoke/api/engines/test_doctor_meta.py yoke/api/engines/test_doctor_hc_db_full.py yoke/api/engines/test_doctor_hc_git_full.py yoke/api/engines/test_doctor_hc_meta_full.py yoke/api/engines/test_doctor_project_full.py yoke/api/engines/test_doctor_filesystem_full.py --cov=runtime.api.engines.doctor --cov-report=term-missing -q` | `80.01%` | meets goal |

Summary:
- `7/7` target modules now clear the `>80%` bar.
- `doctor` is the narrowest pass: `1829/2286` statements covered (`80.01%`). `pytest-cov` rounds that display to `80%`, but the exact ratio is above the ticket threshold.

## Verification Snapshot

Most recent verification snapshot from the `YOK-1246` worktree:

| Command | Result |
| --- | --- |
| `python3 -m pytest yoke/api -q` | `3188 passed in 83.49s` |
| `python3 -m pytest yoke/api/engines -q` | `631 passed in 6.25s` |
| `python3 -m pytest yoke/api/test_epic.py yoke/api/test_epic_full.py -q` | `212 passed in 36.71s` |
| `python3 -m pytest yoke/api/engines/test_resync.py yoke/api/engines/test_resync_full.py -q` | `131 passed in 0.40s` |
| `python3 -m pytest yoke/api/engines/test_doctor_db.py yoke/api/engines/test_doctor_git.py yoke/api/engines/test_doctor_meta.py yoke/api/engines/test_doctor_hc_db_full.py yoke/api/engines/test_doctor_hc_git_full.py yoke/api/engines/test_doctor_hc_meta_full.py yoke/api/engines/test_doctor_project_full.py yoke/api/engines/test_doctor_filesystem_full.py -q` | `442 passed in 1.15s` |
| `python3 -m pytest yoke/api/test_backlog_github_sync.py -q` | `3 passed in 0.09s` |
| `python3 -m pytest yoke/api/test_epic_task_sync.py -q` | `11 passed in 0.12s` |
| `python3 -m pytest yoke/api/test_update_status.py -q` | `32 passed in 0.27s` |
| `python3 -m pytest yoke/api/test_update_status_full.py -q` | `26 passed in 49.88s` |
| `python3 -m pytest yoke/api/test_update_status.py yoke/api/test_update_status_full.py -q` | `58 passed in 51.49s` |
| `python3 -m pytest yoke/api/test_merge_worktree_full.py -q` | `56 passed in 237.05s` |
| `python3 -m pytest yoke/api/engines/test_repair_status.py -q` | `5 passed in 0.15s` |
| `python3 -m pytest yoke/api/test_backlog.py yoke/api/test_service_client.py yoke/api/test_backlog_github_sync.py -q` | `203 passed in 34.57s` |
| `python3 -m pytest yoke/api/test_emit_event.py yoke/api/test_events.py yoke/api/test_events_crud.py yoke/api/test_events_crud_full.py -q` | `190 passed in 0.93s` |
| `sh .agents/skills/yoke/scripts/tests/test-backlog-label-sync.sh` | `44 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-backlog-registry-sqlite.sh` | `205 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-backfill-task-labels-status.sh` | `9 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-dedup-github-issues.sh` | `47 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-frozen-label-sync.sh` | `10 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-sync-to-github-cross-project.sh` | `6 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-sync-progress-cross-project.sh` | `6 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-sync-task-label.sh` | `14 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-sync-body-task.sh` | `18 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-yoke-db.sh` | `91 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-update-status.sh` | `21 successful, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-merge-worktree.sh` | `16 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-repair-status.sh` | `11 passed, 0 failed` |
| `sh .agents/skills/yoke/scripts/tests/test-lifecycle-mutation-guard.sh` | `15 passed, 0 failed` (`repair-status` subcase skipped because the isolated item bootstrap did not materialize) |
| `sh .agents/skills/yoke/scripts/tests/test-yoke-db-events.sh` | `124 passed, 0 failed` |

## Timing Snapshot

Goal from `YOK-1246`: capture before/after timing evidence for the heaviest
legacy shell suites.

The table below compares the pre-1246 merge-base baseline (`151a9a694`,
measured from `/Users/dev/yoke`) against the current `YOK-1246`
worktree. This is enough to evaluate the ticket's timing claim honestly.

| Surface | Baseline command / result | Baseline time | Current command / result | Current time | Outcome |
| --- | --- | ---: | --- | ---: | --- |
| observe replacement | branch-point legacy observe shell benchmark -> `142 passed, 0 failed` | `17.80s` | `python3 -m pytest yoke/api/test_observe.py yoke/api/test_observe_full.py -q` -> `157 passed` | `0.41s` | improved by ~97.7% |
| resync replacement | branch-point legacy resync shell benchmark -> harness breaks immediately from retired sprint/schema assumptions | `0.67s` to failure | `python3 -m pytest yoke/api/engines/test_resync.py yoke/api/engines/test_resync_full.py -q` -> `131 passed` | `0.40s` | baseline unrecoverable at branch point |
| epic replacement | branch-point legacy epic shell benchmark -> `288 passed, 2 failed` (stale shell expectations) | `27.78s` | `python3 -m pytest yoke/api/test_epic.py yoke/api/test_epic_full.py -q` -> `212 passed` | `36.71s` | slower by ~32.1% |
| `update-status` replacement | `/usr/bin/time -p sh .agents/skills/yoke/scripts/tests/test-update-status.sh` -> `116 passed, 0 failed` | `130.04s` | shell smoke `21 passed` in `8.34s` + pytest `58 passed` in `52.19s` | `60.53s` combined | improved by ~53.5% |
| `merge-worktree` replacement | `/usr/bin/time -p sh .agents/skills/yoke/scripts/tests/test-merge-worktree.sh` -> `142 passed, 0 failed` | `197.17s` | shell smoke `16 passed` in `19.63s` + pytest `56 passed` in `237.05s` | `256.68s` combined | slower by ~30.2% |

## Post-Zero-Shell Retest (2026-04-11)

Retest conditions on `main` after the literal zero-shell cutover:

- commit: `2a411144b`
- tracked shell files: `git ls-files '*.sh' | wc -l` -> `0`
- measurement method: rerun each surviving Python replacement suite from
  `/Users/dev/yoke` with `/usr/bin/time -p`; keep `pytest` duration for
  continuity with the historical `YOK-1246` table above, but treat wall-clock
  `real` time as the canonical post-cutover number

The `update-status` and `merge-worktree` shell smoke suites used in `YOK-1246`
no longer exist on `main`, so the post-cutover retest covers the surviving
Python suites only.

| Surface | Current command / result | `pytest` time | `real` time | Retest note |
| --- | --- | ---: | ---: | --- |
| observe replacement | `python3 -m pytest yoke/api/test_observe.py yoke/api/test_observe_full.py -q` -> `155 passed` | `0.17s` | `2.42s` | still much faster than the `17.80s` shell baseline; also faster than the `0.41s` `YOK-1246` pytest snapshot |
| resync replacement | `python3 -m pytest yoke/api/engines/test_resync.py yoke/api/engines/test_resync_full.py -q` -> `131 passed` | `0.46s` | `0.68s` | legacy branch-point shell baseline is still unrecoverable; slightly slower than the `0.40s` `YOK-1246` pytest snapshot |
| epic replacement | `python3 -m pytest yoke/api/test_epic.py yoke/api/test_epic_full.py -q` -> `215 passed` | `0.32s` | `2.65s` | now faster than both the `27.78s` shell baseline and the `36.71s` `YOK-1246` pytest snapshot |
| `update-status` replacement | `python3 -m pytest yoke/api/test_update_status.py yoke/api/test_update_status_full.py -q` -> `59 passed` | `12.62s` | `12.84s` | shell smoke retired on zero-shell `main`; surviving Python suite is much faster than the `130.04s` shell baseline and the `51.49s` `YOK-1246` pytest snapshot |
| `merge-worktree` replacement | `python3 -m pytest yoke/api/test_merge_worktree_full.py -q` -> `65 passed` | `105.27s` | `105.54s` | still the slowest path, but now faster than both the `197.17s` shell baseline and the `237.05s` `YOK-1246` pytest snapshot |

## Historical Blockers Carried Forward

- `YOK-1246` is now done on `main`. The items below are no longer blockers for
  that ticket; they are the explicitly accepted follow-on queue.
- `YOK-1322` is now also done on `main`. Fresh real Claude Code and Codex
  sessions proved the final live seam: `harness_sessions.current_item_id` /
  `recent_item_id` now populate in production claim flows, and the final
  done-transition ceremony completed successfully.
- `YOK-1332` remains a follow-on zero-shell lane:
  - AC-3 / AC-4 still require behavioral ownership to keep moving out of shell
    and into pytest
  - `test-backlog-registry-sqlite.sh` is still a heavyweight behavioral shell
    suite, not just wrapper smoke
  - `backlog-registry.sh` still retains a small shell semantic tail
    (`cmd_close`, done-recovery ceremony, and shell-only wrapper glue)
- The timing evidence captured during `YOK-1246` implementation remains
  historically important, and it is now complemented by the 2026-04-11
  post-zero-shell retest on `main`:
  - `observe` improved again
  - `update-status` improved again after the shell smoke path disappeared with
    the literal zero-shell cutover
  - `resync` still has no clean branch-point shell baseline because the old
    suite was already broken at `151a9a694`
  - `epic` is no longer timing-worse than the branch-point shell measurement;
    it collapsed from tens of seconds to sub-second `pytest` time
  - `merge-worktree` remains the slowest surviving Python suite, but it is no
    longer slower than the recorded shell baseline
- Legacy/obsolete residue cleanup is broader than `YOK-1246` alone. The
  remaining shell-test, archive, and migration cleanup now belongs to the
  zero-shell continuation.
- The broader zero-shell continuation now lives in the next-wave tickets in
  `shell-inventory.md` plus endgame follow-ons such as `YOK-1189`,
  `YOK-1265`, and `YOK-1300`.

## Tracked Follow-On: Identifier Normalization

This is intentionally tracked here as follow-on work, not as a hidden cleanup
inside `YOK-1246`.

- `events.item_id` machine storage is now normalized on `main`:
  - `0` prefixed `YOK-%` rows remain in top-level or JSON item-id fields
  - true backlog item references are stored numerically
- `work_claims.item_id` is also normalized on `main`:
  - `0` prefixed `YOK-%` rows remain
  - live claim storage is numeric for backlog items
- The system is currently overloading `item_id` for two different concepts:
  - true backlog item references
  - generic work-unit identifiers used by sessions / claims / routing surfaces
- The cleanup should therefore be a deliberate split, not a blind global purge:
  - normalize true backlog item references to numeric form internally
  - rename generic work-unit surfaces to a clearer identifier such as
    `work_unit_id`
  - keep `YOK-N` only at human-facing parse/render boundaries

This should be handled as a dedicated follow-on refactor in the broader
zero-shell / cleanup continuation, not by reopening the completed
`YOK-1246` / `YOK-1322` phase.
