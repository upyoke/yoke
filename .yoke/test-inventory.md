# Test Inventory: Yoke

This inventory documents the Yoke test surfaces agents should reason about
when planning, conducting, polishing, merging, and deploying Yoke work.
Executable command definitions live in Yoke DB/project structure records;
this file explains intent.

## Local Test Surfaces

| Surface | Command shape | Purpose |
| --- | --- | --- |
| Focused pytest | `python3 -m pytest <targeted files>` | Fast verification for touched Python modules. |
| Domain pytest | `python3 -m pytest runtime/api/domain/...` | Domain behavior, schema, gates, claims, and handlers. |
| Tool pytest | `python3 -m pytest runtime/api/tools/...` | CLI/tooling behavior, watchers, renderers, and install helpers. |
| Codex harness pytest | `python3 -m pytest runtime/harness/codex/test_codex_entry.py` | Codex harness launcher bootstrap and command routing. |
| Full local suite | `python3 -m pytest` | Broad Postgres-backed regression proof. |
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
