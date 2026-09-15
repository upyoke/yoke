# Test Inventory: Yoke

This inventory documents the Yoke test surfaces agents should reason about
when planning, conducting, polishing, merging, and deploying Yoke work.
Executable command definitions live in Yoke DB/project structure records;
this file explains intent.

## Local Test Surfaces

| Surface | Command shape | Purpose |
| --- | --- | --- |
| Change-scoped selection | `yoke watch pytest --impacted main --bounded` | Default verification; on a project with CI this runs remotely. |
| Small targeted pytest | `yoke watch pytest --local -- <one file>` | Local only when the whole invocation is expected to finish in about one minute. |
| Domain pytest | `yoke watch pytest -- runtime/api/domain/...` | Domain behavior; use CI unless the run is a small targeted check. |
| Tool pytest | `yoke watch pytest -- runtime/api/tools/...` | CLI/tooling; same CI-vs-fast-local rule. |
| Codex harness pytest | `yoke watch pytest -- runtime/harness/codex/` | Codex harness; same CI-vs-fast-local rule. |
| Full suite | `yoke watch pytest -- runtime/api/ runtime/harness/ tests/` | CI on the protected merge path; local only as the CI-outage fallback. |
| Render/check tools | `agents.render.check`, `atlas_render_docs --check`, related checks | Generated packet/docs drift detection. |

## Lifecycle Placement

| Yoke moment | Expected verification |
| --- | --- |
| Implementing | Run focused tests near the changed surface. |
| Reviewing implementation | Tester runs the command definition scope appropriate to risk. |
| Integration | Re-run touched families after branch integration. |
| Release | Deployment flow runs migration/deploy/smoke stages once cloud runtime is owned. |

## Postgres Assumption

Yoke authority is Postgres-native. Local tests use a disposable Postgres
cluster, an explicit Postgres DSN, or the connected cloud authority when that
is the intended operator path. SQLite appears only in classified external
validation/import/test-double boundaries, not as Yoke runtime authority.

## Evidence

Durable evidence belongs in Yoke DB QA/deployment records with artifact
handles. Raw screenshots, traces, logs, and command captures belong under the
configured temp root, not under this contract directory.
