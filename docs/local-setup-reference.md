# Local Setup Reference

This companion keeps detailed configuration, agent-host, and source-development
reference material separate from the primary product setup path.

### What Project Install Writes

`yoke project install` fetches the active env's install bundle and writes the
project-local operating layer:

- Yoke skills under `.claude/skills/yoke/` and `.codex/skills/yoke/`.
- Rendered agent adapters under `.claude/agents/` and `.codex/agents/`.
- Hook entries merged into `.claude/settings.json` and `.codex/hooks.json`.
- Git hook shims for the installed guardrails.
- `.yoke/install-manifest.json` for refresh and uninstall tracking.
- Seed-if-missing project contract files under `.yoke/`.
- DB-rendered strategy views under `.yoke/strategy/`.

Refresh and uninstall are manifest-tracked:

```bash
yoke project refresh ~/work/my-app --config ~/.yoke/config.json
yoke project uninstall ~/work/my-app --config ~/.yoke/config.json
```

### Preview an Unshipped Source Refresh

Yoke developers can preview the project layer from one explicit local Yoke
checkout before that code ships. This is a source-dev/admin surface; ordinary
project refresh continues to fetch the active environment's packaged bundle.
Preview is the default and performs no target, machine-config, environment, or
snapshot-state writes:

```bash
yoke project refresh ~/work/my-app \
  --source-checkout ~/work/yoke \
  --project-id 7 \
  --project-slug my-app \
  --json
```

After inspecting the preview, repeat it with `--apply`. A linked project
worktree normally lacks the gitignored install manifest, so transfer lineage
explicitly from the main checkout. The transferred hashes preserve the normal
safe-prune behavior; the refreshed manifest is then written in the target
worktree. Apply refuses a target with neither its own manifest nor an explicit
`--manifest-from` source.

```bash
yoke project refresh ~/work/my-app/.worktrees/source-proof \
  --source-checkout ~/work/yoke \
  --manifest-from ~/work/my-app/.yoke/install-manifest.json \
  --project-slug my-app \
  --apply \
  --json
```

The local-source apply reads only the named source checkout and writes only the
named project checkout. It does not fetch or update environment bundle state,
register the checkout in machine config, or sync snapshots. Its subprocess
refuses source imports that originate anywhere other than the explicit
checkout. Project contract and strategy files are preserved because their
rendering requires project DB authority. Prior managed files outside the
source-rendered skill, agent, and rule namespaces (for example, a
project-specific deployment workflow) remain tracked at their prior manifest
hash and are neither rewritten nor pruned. Legacy manifests do not record the
real project slug, so pass `--project-slug`; current refreshes persist it for
later runs.

Project install/refresh also verifies that the `yoke-harness` product package
is importable before writing files or git hook shims. If that check fails,
rerun the public installer; `yoke status --json` reports the missing package as
an error instead of declaring the product environment healthy.

Project-owned contract files are preserved once edited. Generated board views,
credentials, runtime directories, and machine config are not installed into the
repo by the project bundle.

## Configuration Model

Machine-local runtime context lives in `~/.yoke/config.json`. It owns the
active env, credential source, temp/cache roots, checkout-to-project
bindings, board render path, and physical worktree layout.

Project-local configuration lives in the project checkout:

- `.yoke/board.json` controls board rendering appearance and behavior.
- `.yoke/board-art` contains board presentation variants.
- `.yoke/lint-config` and `.yoke/labels` carry guardrail and label policy.
- `.yoke/runbooks/` is project-owned onboarding context; `.yoke/strategy/`
  holds untracked rendered views of the DB-authoritative strategy docs.

Shared project behavior lives in the Yoke DB, not checkout files:

- `project-policy` capability settings own `base_branch`, `wip_cap`,
  `default_priority`, `merge_conflict_threshold`, `max_attempts`, and
  `file_line_limit`. They may also set
  `artifact_refresh.enabled=false` with a non-empty
  `artifact_refresh.reason` when a project-owned release factory replaces the
  generic webapp artifact contract.
- `session-routing` capability settings own default lanes, lane path
  allowlists, and `/yoke do` process-offer policy.

Managed delivery artifacts have a separate template-render boundary from the
operating substrate. Preview, apply, and verify them with:

```bash
yoke project artifacts refresh /path/to/project --project <slug>
yoke project artifacts refresh /path/to/project --project <slug> --apply
yoke project artifacts refresh /path/to/project --project <slug> --verify
```

The server renders from its active packaged template plus DB-backed project
settings over HTTPS or self-hosted transport. Before planning, the client
requires the checkout's installed project id to match the server bundle. When
the project has a verified repository binding, its live Git origin must also
match exactly; local/offline projects without that optional binding still use
the durable installed project identity. The source-dev template-tree override
requires both its explicit flag and org-admin authority, and never bypasses
checkout identity.

When DB policy marks the generic artifact contract non-applicable, preview,
apply, and verify still validate checkout identity, then return a clean no-op
receipt with the configured reason. They do not inspect or write the artifact
manifest and do not materialize webapp workflows or infrastructure.

The client preserves local deviations and refuses apply, validates the complete
manifest/path/symlink plan before any write, and prunes only unchanged files
owned by its manifest. Project-authored `.yoke/runbooks/` remain outside the
managed set; generic rendered references land under
`docs/yoke-generated/deployment-reference/`. `yoke project refresh` remains
substrate-only. Pulumi stack YAML stays on the exact stack-config and
`yoke pulumi exec` surfaces so operator state is never copied into the generic
artifact manifest.

Generated views such as `.yoke/BOARD.md` are read-only output. Regenerate
them through Yoke commands; do not edit them directly.

Inspect the current machine and project binding with:

```bash
yoke status
yoke projects checkout-context
```

## Local Core Product Launcher

Machines that need a self-hosted local Yoke API use the product `yoke core`
launcher. This is the explicit source-dev/admin local-core path; it does not
grant normal operators direct DB authority, and it does not pull a public
default core image.

```bash
yoke core build --checkout /path/to/yoke --dry-run
yoke core start --from-checkout /path/to/yoke --build
yoke core status --json
yoke core logs
yoke core stop
yoke core upgrade --from-checkout /path/to/yoke --build --dry-run
```

State lives under `~/.yoke/local-core`. Start with a dry run when Docker,
Colima, or local runtime state is uncertain. Use `--image IMAGE` only when an
already-built local/private Yoke core image should be run directly.

## Agent Hosts

Yoke runs inside supported harnesses through installed project skills and
hooks.

- **Claude adapter:** open the installed project checkout and use `/yoke ...`
  slash commands.
- **Codex adapter:** open the installed project checkout; Codex reads the
  installed `.codex/` skills and hooks.

First project adoption after install should start with:

```text
/yoke onboard-project --project-root <checkout> --run-id <run-id>
```

After adoption, normal item flow is:

```text
/yoke idea "my first item"
/yoke advance YOK-N implementing
/yoke usher YOK-N
```

## Yoke Source-Dev/Admin Setup

Use this lane only when you are editing Yoke itself, maintaining install
bundles, running server-side provisioning, or developing the CLI/core.

Start with the product setup above, then install the Yoke source checkout as
a normal project:

```bash
git clone git@github.com:upyoke/yoke.git ~/yoke
yoke project install ~/yoke \
  --project-id <yoke-project-id> \
  --config ~/.yoke/config.json
```

Then run the explicit source-dev setup:

```bash
yoke dev setup ~/yoke \
  --config ~/.yoke/config.json \
  --set-active-env
```

Useful source-dev flags include `--editable-install`, `--with-test-postgres`,
and the tunnel or authority flags shown by `yoke dev setup --help`.

`--editable-install` runs `pip install -e` for the four packages and then
replaces pip's absolute-path editable artifacts with a config-driven shim
(`_yoke_editable.pth` + `_yoke_editable_loader.py` in site-packages). The shim
resolves the checkout root at each interpreter start from `YOKE_REPO_ROOT`, then
machine config (`~/.yoke/config.json`), then an install-time fallback — so moving
or renaming the checkout only needs the machine-config path updated, with no
reinstall. A bare `pip install -e` (without `yoke dev setup`) still bakes the
absolute path and must be rerun after a move.

`yoke status` states which binding is live on its `install:` line —
`packaged wheel <version>` or `source checkout <path>`. The binding only
changes through this explicit setup; a checkout's presence on disk activates
nothing.

Source-dev/admin-only work includes:

- Building or publishing with `uv run python -m yoke_core.tools.build_release`;
  product wheels exact-pin sibling `Requires-Dist` to prevent substitution.
- Updating install bundles and rendered agent packets.
- Minting actor tokens and granting roles for a deployed env.
- Creating or repairing server-side project rows, capabilities, and deployment
  flows when product `project create/import/onboard` cannot reach the target
  env.
- Running migrations, Postgres backup/restore, or direct DB diagnostics.
- Recovering stale sessions or other server-side state.

Do not teach these as normal project setup. Normal operators use
`yoke onboard`, `yoke status`, project create/import/onboard/install, and
the durable checklist handoff.
