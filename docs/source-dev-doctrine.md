# Source-dev doctrine — working on Yoke itself

Repository-only rules; linked owners hold the detail.

## Run source and tests

- Run lane commands as `yoke dev run -- <command>`. It binds the claimed lane's source and locked
  `.venv`, runs in a disposable machine home, and refuses partial binding. Owner:
  [source command guide](testing-verification/source-development.md).
- Plain `yoke` runs the installed release. `YOKE_SOURCE_DEV=1 yoke <command>` is an explicit
  per-command operator opt-in.
- Before the QA case, iterate with `yoke watch pytest --impacted main --bounded` or targeted
  paths. It runs on CI (commit first) and defers to full CI.
- `--local` is only a small targeted check expected to finish in about one minute; uncommitted
  work does not justify a slow local run. Both shapes inject xdist `-n auto`. Use `-- -n 0` for
  order-sensitive debugging.
- Full gate: plan `registered-command-full` (`command-ci`); a `worktree_run` copy refuses
  `redundant_full_suite`. Run it once: `yoke qa requirement list --item PREFIX-N`;
  `yoke qa case run --requirement-id <id>`. Owner:
  [full-suite authority](testing-verification/full-suite-authority.md).
- Command cases can run `yoke dev run -- <command>`: it selects the claimed lane before
  merge and the bound candidate after merge. `yoke watch pytest -- <paths>` also binds the
  candidate. Keep `YOKE_QA_CANDIDATE_TREE` and the runner's environment when you replace `HOME`.
- Lint: `yoke dev ruff-changed --base <ref>`. Smoke-import lane modules with
  `yoke dev import-check <module>`. The generic runner is
  `uv run --frozen python3 -m yoke_core.tools.run_tests`. Recipes:
  [testing and verification](testing-verification.md).
- Never set `YOKE_DRY_RUN=1` in tests; suites mock their own GitHub side effects.

## Database authority

- HTTPS `prod` owns registered operations. Paired `prod-db-admin` runs handlers locally over
  a tunnel; any call outside `yoke_contracts.direct_database_access` refuses
  `use_https_env`. Every real record stays on prod, including stage receipts. Stage is
  disposable. Connections: `yoke env list`.
- Platform's database (`yoke_platform`) is read-only here:
  `yoke --env platform-prod-registry-db-admin db read "SELECT ..."` (stage:
  `platform-stage-registry-db-admin`).
- Raw query is read-only. A sanctioned row repair with no domain command uses
  `yoke operator data-repair --content-file repair.json --reviewed-sha256 SHA --dry-run` from a
  live steering seat after the operator approves the digest; then rerun without `--dry-run`.
  Owner: [repair contract](public/databases/operator-data-repair.md).
- Only source-dev/admin setup creates admin profiles (see `yoke dev db-admin --help`). Never
  print or store a DSN:

  ```text
  yoke dev db-admin setup prod --control-plane-env prod --yes
  yoke dev db-admin setup stage --project P --database MODEL --yes
  yoke dev db-admin exec P-stage-MODEL-db-admin --dsn-var APP_DSN -- <command>
  ```
- Rehearse migrations from the claimed lane:
  `yoke dev run -- yoke --env prod-db-admin migration rehearse PREFIX-N`. With several lanes add
  `--lane <registered-worker-path>` after `dev run`. Keep the fleet-preflight receipt and the
  `LIVE_DB_MIGRATION:<model>` hold; the merge releases it.
- Tenant-fleet content-identity adoption is an attested operator step: read
  `python3 -m yoke_core.tools.adopt_migration_content_identity --help`.
- After schema declaration changes, regenerate the serving catalog and commit it with the change:
  `yoke dev run -- python3 -m runtime.api.tools.schema_catalog_render --target-root <checkout>`.

## Release Yoke

- Steering drives a release: two concurrent runs on one lineage, both created over HTTPS
  `prod`. LINEAGE is production's `release_lineage`. Production drives on `prod-db-admin` (it
  replaces its own API; try `prod` first); stage on `prod`. Resume with the same run and key:

  ```text
  yoke --env prod deployment-runs create yoke FLOW --environment prod --idempotency-key KEY
  yoke --env prod deployment-runs create yoke STAGE_FLOW --environment stage --project-repo-path CHECKOUT --source-ref LINEAGE --idempotency-key STAGE_KEY
  yoke --env prod-db-admin watch deploy -- PROD_RUN
  yoke --env prod watch deploy -- STAGE_RUN
  ```
- Done needs production delivery and every owed stage proof. This concurrency holds only because
  stage here tests the live control plane.
- A correction merged during a stage run needs a new stage/production pair on the corrected
  commit; the old stage receipt does not prove it.
- Author item QA against production. A case targets stage only with a declared `stage_reason`.
- Hosted routes: `yoke-hosted-stage-release-qa`, `yoke-hosted-production-release-qa`,
  `yoke-hosted-production-hotfix-release`. Never hand-create release tags, hand-edit
  `yoke-release-pin.txt` or dispatch component deploy workflows. Pin owner:
  [release pin recording](release-pin-recording.md).
- One Yoke release ships Platform at the `main` commit the run bound at start; delivery-ready
  PLAT items in that commit ride as members. Platform work merged later needs its own run.
  Re-read the pin after any Yoke release before you start a Platform run, and start one only
  when no Platform flow is in flight.
- Consumer proof belongs to release. The bridge runs `platform-release-pin-check.yml` on the
  exact Yoke/Platform pair before tagging. A failed pair names the producer commit range; inspect
  it before you assign the fix. Why:
  [consumer compatibility](archive/decisions/consumer-compatibility-before-contract-delivery.md).
- Fleet preflight: `yoke watch preflight -- --project <project> <environment>`; read its
  `--help` for models and receipts. Owner: [migration fleet](public/databases/migration-fleet.md).
- Release diagnostics and the operator CLI update:
  [start diagnostics](public/deployments/start-diagnostics.md).

### Creation bootstrap

If run creation needs a merged fix the serving API predates, steering may bootstrap creation from
a clean checkout at that exact reviewed commit with its own green CI run. Use the explicit
launcher script, not a `yoke` console entrypoint. Run it with `deployment-runs create --help`
first: it must print `source authority: explicit operator opt-in`. Keep the same idempotency key
on retries. Workers report the need to steering; they do not run it.

```text
c=/absolute/source/checkout
env YOKE_SOURCE_DEV=1 YOKE_HOME="$c" "$c/.venv/bin/python3" \
  "$c/packages/yoke-core/src/yoke_core/tools/yoke_launcher.py" \
  --env prod-db-admin deployment-runs create yoke FLOW --environment prod \
  --project-repo-path "$c" --source-ref FULL_SHA --idempotency-key KEY
```

## Code rules for this repo

- CLI usage: [authoring and checks](source-dev/cli-usage-contract.md).
- Compose refusals through `yoke_contracts.refusal_recovery.compose_refusal`.
- Declare a new function's `minimum_serving_version` on its registry entry and in
  `yoke_contracts.function_serving_floors.FUNCTION_MINIMUM_SERVING_VERSIONS`; older engines
  refuse `function_version_skew`. New fields degrade to prior behavior or refuse with a named
  floor; never invent required receipt defaults. Order rollout so live clients work during
  serving/DB convergence. Floor recovery cannot depend on the missing function or its deploy.
- Shell classification reuses `lint_shell_path_use.analyze_shell_path_use` and
  `lint_payload_path_use.extract_payload_path_uses`; no second parser or broad read exception.

- Product code never branches on a project name. Read the declared fact instead.
  `HC-project-name-literal` enforces it; allowances live in
  `yoke_core.domain.lint_project_name_literal_allowances`.
- A function that runs on a caller's transaction (`commit=False` or a borrowed `conn=`) never
  commits or rolls back. Wrap its writes in `yoke_core.domain.db_savepoint.savepoint`, and re-raise
  `SavepointLostError` before any broad `except`.
- Repo-tree writers take an explicit `target_root` and call the workspace-authority guard. Add new
  writers to `IN_SCOPE_WRITERS`. Owner: [harness substrate](harness-substrate.md).
- A Bash-capable agent needs a `*_agent` packet role and marker pairs. Regenerate with
  `agents.render.run`, check with `agents.render.check`. Owner: [agents](agents.md).
- When a Yoke-owned surface fails with `no such column`, `cannot import name` or
  `unexpected keyword argument`, the same PR names the real surface in its
  `schema_api_context_tables_*.py` entry with a `notes` clause naming the wrong guess.
- Never export session env vars to self-bootstrap identity. Owner:
  [session identity](session-identity-contract.md).
- Scripts that import `runtime.*` live in-tree under `runtime/api/tools/`, never in `/tmp`.
- Client packages (`yoke_contracts`, `yoke_cli`, `yoke_harness`) never import core helpers.

## Repo layout

- Engine: `packages/yoke-core/src/yoke_core/`. `runtime/api/` and `runtime/harness/` hold tests,
  fixtures and tools for the same packages. Resolve modules through the packet's `package_roots`.
- Skills: `.agents/skills/yoke/`. Agents: `runtime/agents/`; adapters via `yoke agents render`.
- Hooks: `runtime/harness/claude/settings.json` and `runtime/harness/codex/hooks.json`.
  Harness manifest schema: `runtime/harness/manifest-schema.md`.
- Install-bundle docs are authored under `docs/public/`. After a change, run
  `yoke dev run -- python3 -m yoke_core.domain.install_bundle_tree_sync sync --target-root <checkout>`
  and commit every changed path together.
- Machine config: `~/.yoke/config.json`; machines: [machine registry](machine-registry.md).

## Review, teaching and cleanup

- Serve a lane's UI: `yoke dev run -- python3 -m runtime.api.tools.serve_workbench_for_review`.
  Commit first; a dirty tree fails the served-commit match. With `env YOKE_ENV=render-proof`,
  add `--prepare-only` to prepare a render universe. Self-hosted sign-in review uses
  `serve_self_host_workbench_for_review` the same way.
- Teaching model: read `docs/teaching/README.md` before changing what Yoke teaches; it owns
  the build and `--check` recipes and `yoke dev yokepedia`.
- Worktree cleanup: [worktree cleanup](source-dev-worktree-cleanup.md).
- `origin/cla-signatures` is permanent governance state. Never delete, force-push, reset, prune or
  protect it.
