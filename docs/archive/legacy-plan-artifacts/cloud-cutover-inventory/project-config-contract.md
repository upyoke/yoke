# Phase 4 — project-level settings contract (B5, Wave 1)

Operator mandate (GEN-3-PLAN, "Remaining Gen 3 work" B5): enumerate EVERY
available project-level setting with defaults and switches; one owner per
setting; settings reachable only through DB rows or code constants with no
config surface are gaps to close. Boundary decision (2026-06-11): project
**policy/preference** lands in repo files; per-environment / secret-bearing
**execution truth** stays in DB rows surfaced via generated views + named CLI
commands; machine-client facts stay in `~/.yoke/config.json`; everything
else is a source default, deliberately not a setting.

Status key: LIVE = works today; GAP-n = build item in this wave's gap list.

## 1. File-owned project settings (repo-rides-policy)

| Surface | Keys | Resolver | Install-seeded | Status |
| :--- | :--- | :--- | :--- | :--- |
| `.yoke/project.config` | `do_process_offer_default`, `do_process_offer_strategize`, `do_process_offer_feed`, `do_process_offer_doctor` | `runtime/api/domain/project_settings.py` (scope-first: project key → project default → machine key → machine default → off) | yes (commented-out, contract-seeding v0) | LIVE |
| `.yoke/board.json` | 30 renderer knobs: `dashboard_weather`, `dashboard_recent_sessions`, `dashboard_velocity_meter`, `dashboard_velocity`, `dashboard_types`, `dashboard_age`, `dashboard_badges`, `dashboard_sessions_scope`, `dashboard_meter_cap`, `timeline_widget`, `timeline_label_days`, `timeline_label_df_cap_pct`, `timeline_label_min`, `timeline_extra_stopwords`, `timeline_scope`, `done_section_limit`, `art_override`, `art_frontier_since`, `art_weight_*` (9 keys) | board renderer config reader (project-local; explicit defaults for every read key) | yes (every knob at default) | LIVE |
| `.yoke/board-art` | art content (not config) | board renderer | yes (generic seed art) | LIVE |
| `.yoke/lint-config` | 26 guard modes (`<guard>=deny\|warn`, protected-guard `# allow-warn` clamp) | lint mode resolver; rendered from `lint_config.GUARD_CATALOG` | yes | LIVE |
| `.yoke/labels` | `label_color_*` = HEX family | GitHub label sync readers | yes | LIVE |
| `.yoke/strategy/*.md` | strategy doc rendered views (content, not settings) | `strategy_docs_paths` seam | yes (`strategy_files` class, db_render) | LIVE |

## 2. Machine-overlay keys that are PROJECT policy (GAP-1: promote)

These read from machine config `settings` today (`runtime_settings.py` →
`~/.yoke/config.json:settings`) but carry per-project semantics — the same
machine working two projects wants per-project values. Promote to recognized
`.yoke/project.config` keys with scope-first resolution (project →
machine → source default), exactly the `do_process_offer_*` pattern:

| Key | Live reads | Per-project because | Source default |
| :--- | :--- | :--- | :--- |
| `base_branch` | 7 call sites | a project's trunk name is project truth (yoke=main, another repo may differ) | `main` |
| `wip_cap` | 3 | backlog WIP policy differs per project | code default |
| `worktrees_dir` | 1 | checkout-layout policy | `.worktrees` |
| `default_priority` | 1 | backlog intake policy | code default |
| `merge_conflict_threshold` | 1 | merge tolerance policy | code default |
| `max_attempts` | 1 | retry policy for project flows | code default |

Stay machine-level (NOT promoted): `monitor_hint_color` (operator UX),
`lint_*_mode` machine clamps (machine dogfood posture; project downgrades go
through `.yoke/lint-config` with server-side protected-guard clamp),
`temp_root`, connections/credentials, checkout→project map.
`default_actor_id` is retired-shape residue — auth binds actors now; GAP-4
deletes the read.

## 3. DB-owned project settings (correct home; visibility duty)

Execution truth stays in DB rows. The contract duty is discoverability, not
relocation:

| Family | Rows | Read/write surface |
| :--- | :--- | :--- |
| Project row | `projects.breakage_policy`, `projects.public_item_prefix`, `projects.slug`, `projects.name`, `projects.org_id` | `db_router` project reads; grant/admin CLIs |
| Capabilities | `project_capabilities` settings per capability (`aws-admin`, `aws-route53`, `ssh`, `github`, `migration_model`, `ci_workflow_file`, `browser-qa`, `ephemeral-env`, `health-endpoint`, `domain`, `webapp-runtime`, `pulumi-state`, `container-registry`) + `capability_secrets` | `capability-get-settings` / `capability-set-settings` / `capability-get-secret` (CAS lands in Wave-1 S2) |
| Environments | `environments.settings` (hosts, servers, database, pulumi, git.branch, deploy.auto_on_push) | `environment-get-settings` / `environment-set-settings` (CAS lands in S2) |
| Sites | `sites.settings` (domains[], cdn) | projects CLI |
| Project structure | `command_definitions`, `merge_verification`, `context_routing`, `architecture_model` | `project_structure` function family |

GAP-2: none of these are enumerable from a project checkout without knowing
the command names. Close by teaching: a "where settings live" section in the
seeded `.yoke/README.md` naming every family above with its read command
(generated `.yoke/generated/**` views stay deferred per plan — the README
teaching is the v0 closure).

## 4. Deliberately NOT settings (source defaults)

Per the §2.P disposition table (executed in I4A): lock/retry tunables,
session staleness windows, hook timeout budgets, watcher cadence, scheduler
internals. These are code constants on purpose; absence from config surfaces
is a decision, not a gap. Any future promotion follows the GAP-1 pattern.

## 5. Gap list (build items, this wave)

- **GAP-1** — recognize the six §2 keys in `.yoke/project.config`
  scope-first resolution; thread the six call sites through a
  project-aware reader; seed the keys commented-out with defaults.
- **GAP-2** — `.yoke/README.md` seeded section: "where every setting
  lives" (file families + DB families + read/write commands).
- **GAP-3** — `.yoke/project.config` seed enumerates EVERY recognized
  key (autonomy family + GAP-1 keys), not just the autonomy family.
- **GAP-4** — delete the dead `default_actor_id` machine-settings read
  (auth owns actor binding).
- **GAP-5** — (from file inventory, see `file-inventory.md` beside this
  doc) any bundle-shipped surface the installer still misses.
