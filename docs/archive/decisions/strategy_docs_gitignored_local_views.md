# strategy_docs_gitignored_local_views — the rendered views are gitignored caches

- date: 2026-07-08
- scope: `.yoke/strategy/*.md` git treatment, the committed-view lint apparatus, archive routing, and the strategize approve/commit flow

## Decision

A project's `.yoke/strategy/*.md` rendered views are **gitignored local
caches**, not tracked files. The `strategy_docs` DB table is the sole durable
authority; the views are re-rendered on demand from it. The ignore comes from
the seeded `.yoke/.gitignore` `strategy/` rule (rendered from
`yoke_contracts.project_contract.install_policy.YOKE_TREE_IGNORED_NAMES`), so
**every** newly-installed project ignores the subtree. `reconcile_gitignore`
(in `yoke_cli.project_install.files`) backfills the line into an existing
project's `.yoke/.gitignore` on install/refresh, closing the seed-if-missing
gap for projects onboarded before the rule existed.

## Why

The views were untracked when the strategy corpus was relocated out of the
product tree: the DB became the per-project authority, and keeping a committed
mirror added churn (every render bumped a tracked file) and a second source of
truth. Git history of the DB rows is unnecessary — the DB is authoritative and
the `SMLChangeApproved` / `StrategyDocReplaced` events are the change ledger.

## Consequences

- **`HC-strategy-render-staleness` is the one live verifier.** It reads the
  files directly off disk (gitignore-independent) and compares each doc's
  YOKE:STRATEGY-DOC header against its DB row. It stays authoritative and is
  archive-aware (an archived row is checked at `.yoke/strategy/archive/<slug>.md`).

- **The strategize approve phase no longer commits the views.** `git add
  .yoke/strategy/` stages nothing under the ignore rule, so the old commit step
  would fail on an empty commit. The DB write plus the `SMLChangeApproved` event
  is the durable record. `_commit_sha` is retained as `""` in the strategize
  event contexts for backward compatibility with existing consumers rather than
  ripped out of two event emissions.

- **Archived docs inherit the same treatment.** `strategy.doc.archive` routes a
  doc to `.yoke/strategy/archive/<slug>.md`, already covered by the
  directory-level `strategy/` ignore rule — no separate ignore entry, and the
  shallow top-level orphan scan in the staleness HC intentionally excludes it.

- **The committed-view lint apparatus is now inert, and its retirement is
  deferred.** Because gitignored paths never enter the staged set, the
  main-commit strategy-freshness deny (`lint_main_commit_strategy_freshness` via
  `lint_main_commit`), the matches-the-master authorization
  (`lint_main_commit_process_claims.is_strategy_commit_authorized`), and the
  merge-preflight `_strategy_view_drift_check`
  (`merge_worktree_prepare_preflight`) are all structural no-ops. They are left
  in place rather than deleted in this change: the freshness module shares its
  row loader and blob-freshness helpers with the still-referenced process-claims
  authorization, and the authorization is woven into the core `lint_main_commit`
  deny logic, so a correct retirement is a dedicated refactor with its own test
  surface (`test_lint_main_commit_strategy_freshness*`,
  `test_lint_main_commit_one_call`). Retiring the whole apparatus at once — the
  freshness deny, the matches-master authorization, the strategy-blob plumbing
  in `lint_main_commit`, the merge preflight, the shared helper modules, the
  `STRATEGY_FRESHNESS_SUPPRESSION` token and its `session.md` bullet, and the
  tests — is tracked as follow-up. Being inert, the dead apparatus is harmless
  in the interim (it can only fail-open).
