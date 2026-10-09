# Published workflow update function calls

Yoke publishes each built-in workflow's definition as a sequence of canon
generations. A universe numbers its own workflow versions, so where it stands
against the canon is answered by digest, never by version number. These
function ids list that standing, preview and take updates, and choose whether
the next generation arrives by itself. All take `target.kind='global'`.

| Function id | claim_required_kind | Handler | Notes |
|---|---|---|---|
| `workflows.version.publish` | `None` | `yoke_core.domain.handlers.workflows_publication` | Full `definition`, `workflow_id`, `reason`, optional `expected_current_version` and `keep_current`. Existing workflows require an expected version; new ids omit it. Appends immutable content and actor/reason audit. Default selects it and stops canon-follow; append-only preserves current and follow. Existing item pins stay unchanged. Receipt: `workflow_id`, `version`, `version_id`, `definition_digest`, `current`. |
| `workflows.canon_status.list` | `None` (read) | `yoke_core.domain.handlers.workflows_canon_status` | One row per workflow with a published canon: `workflow_id`, `name`, `current_version`, `state` (`up_to_date`, `update_available`, `customized`, `customized_update_available`), `follow`, `latest_canon_version`, `pending`, plus `current_canon_version` or `derived_from_canon_version`. `pending_only` narrows to the two update-available states. A locally authored workflow is not listed. |
| `workflows.canon_update.preview` | `None` (read) | `yoke_core.domain.handlers.workflows_canon_update` | The three-way merge a take would publish — `taken`, `kept`, `conflicts`, and the merged `definition` — without publishing it. An up-to-date or canon-less workflow refuses as `not_found`. |
| `workflows.canon_update.apply` | `None` | same module | Takes the newest generation for one workflow, preserving local edits, guarded by `expected_current_version`. Publishes a new version, or selects an existing row already holding the merged definition. Receipt: `workflow_id`, `version`, `version_id`, `definition_digest`, `canon_version`, `taken`, `kept`. A conflicting merge refuses as `incompatible`, naming each conflicting path. |
| `workflows.canon_update.apply_all` | `None` | same module | `workflows: [{workflow_id, expected_current_version}, ...]`; each entry is attempted on its own and reported in `applied` (apply's receipt) or `refused` (`workflow_id`, `code`, `message`). Applied entries stay committed when another refuses. A workflow named twice refuses as `payload_invalid`. |
| `workflows.canon_follow.set` | `None` | `yoke_core.domain.handlers.workflows_canon_follow` | `follow: auto|manual`. Receipt: `workflow_id`, `follow`, `previous_follow`. Publishing a local edit as current or selecting an older generation turns following off; this is the only write that turns it back on, and it adopts nothing until the next boot or an explicit apply. |

The writes require org-admin authority. `workflows.canon_status.list` declares
`minimum_serving_version`; a client calling a server that predates it refuses
with `function_version_skew` naming both engine versions.

## CLI adapters

```text
yoke workflows version publish WORKFLOW --definition-file F --reason TEXT [--expected-current-version N] [--keep-current] [--json]
yoke workflows canon-status list [--pending] [--json]
yoke workflows canon-update preview WORKFLOW [--json]
yoke workflows canon-update apply WORKFLOW --expected-current-version N [--json]
yoke workflows canon-update apply-all WORKFLOW=VERSION [WORKFLOW=VERSION ...] [--json]
yoke workflows canon-follow set WORKFLOW (auto|manual) [--json]
```

`apply-all` exits non-zero when any entry refused, in human and `--json`
mode alike, and names `canon-update preview` for each refused workflow. The
Workbench **Workflows** page calls the same function ids.
