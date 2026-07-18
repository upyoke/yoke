# Reserved Fields for DR-1 / QA-1

Downstream epics that add domain-specific events MUST use the existing `events` table and follow the contract. No new tables should be created for temporal event data. Cross-link back from [event-contract.md](../event-contract.md) for the envelope structure, naming conventions, execution context fields, and registry rules these fields plug into.

## DR-1: Delivery Runtime Redesign

DR-1 will emit deployment lifecycle events. Reserved conventions:

| Field | Usage |
|-------|-------|
| `event_kind` | `workflow` |
| `event_type` | `deployment_started`, `deployment_stage_completed`, `deployment_failed`, `deployment_succeeded` |
| `event_name` | `DeploymentStarted`, `DeploymentStageCompleted`, `DeploymentFailed`, `DeploymentSucceeded` |
| `item_id` | The backlog item being deployed, stored in canonical bare-numeric form |
| `project` | Project being deployed |
| `context.detail.deployment_run_id` | UUID identifying the deployment run (correlates all stages) |
| `context.detail.flow_id` | Deployment flow definition ID |
| `context.detail.stage` | Stage name within the flow |
| `context.detail.executor` | Executor type (`auto`, `script`, `health-check`, `github-actions-workflow`) |
| `context.detail.result` | `success`, `failure`, `skipped` |

DR-1 authors can emit these events immediately through the standard event path - no additional code changes are needed. The `lifecycle` and `workflow` kinds are already accepted. Register new event names in `event_registry` before first emission through the source-dev/admin registry workflow.

## QA-1: Unified QA Platform

QA-1 will emit test/review lifecycle events. Reserved conventions:

| Field | Usage |
|-------|-------|
| `event_kind` | `workflow` |
| `event_type` | `qa_run_started`, `qa_run_completed`, `qa_verdict_rendered` |
| `event_name` | `QaRunStarted`, `QaRunCompleted`, `QaVerdictRendered` |
| `item_id` | The backlog item under test, stored in canonical bare-numeric form |
| `task_num` | Epic task number (for epic-scoped QA) |
| `project` | Project under test |
| `context.detail.qa_run_id` | UUID identifying the QA run |
| `context.detail.qa_kind` | `implementation_review`, `simulation`, `smoke_test`, `e2e` |
| `context.detail.verdict` | `PASS`, `FAIL` |
| `context.detail.agent` | Agent that performed the QA (e.g., `tester`, `simulator`) |

QA-1 authors can emit these events immediately through the standard event path. Register new event names in `event_registry` before first emission through the source-dev/admin registry workflow.

## How to Emit a New Domain Event

1. **Register the event** in the `event_registry` table. This is a source-dev/admin boundary, not an installed external-project recipe: add the event to the authoritative registry seed/discovery source in the Yoke checkout, run the registry population flow from that checkout, and commit the resulting catalog update. DB-admin one-offs stay in operator-debug runbooks until a product `yoke events registry ...` writer exists.

2. **Emit the event** using the sanctioned CLI surface:
   ```sh
   yoke events emit \
     --name "DeploymentStarted" \
     --kind workflow \
     --type deployment_started \
     --source-type system \
     --severity INFO \
     --outcome completed \
     --item-id "42" \
     --context '{"deployment_run_id":"uuid-here","flow_id":"external-webapp-prod","stage":"build"}'
   ```

3. **Query the event** using the sanctioned read surface:
   ```sh
   yoke events query --event-name DeploymentStarted --item 42 --limit 5
   ```

No schema changes are needed. The `events` table, event validation, and `event_registry` enforcement already support arbitrary new event kinds and types within the existing taxonomy.
