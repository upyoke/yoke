# Yoke API

FastAPI control plane service for Yoke's software delivery state. Runs as a localhost service on port 8765 and reads/writes the connected Postgres authority.

## Prerequisites

- Python 3.9+
- pip

## Setup

```bash
# Option 1: Install as editable package from repo root (recommended):
pip install -e .

# Option 2: Install dependencies directly:
pip install -r runtime/api/requirements.txt
```

The editable install makes `yoke_core.domain` importable as a proper Python package from anywhere, which is the recommended setup for development and IDE support.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `YOKE_PG_DSN` / `YOKE_PG_DSN_FILE` | connected environment binding | Postgres authority connection override for tests/operator diagnostics |
| `YOKE_API_PORT` | `8765` | Port for uvicorn to listen on |
| `YOKE_API_HOST` | `127.0.0.1` | Host/interface to bind to |

## Running

Start the server:

```bash
python3 -m yoke_core.tools.api_server start
```

Restart (kill existing + start fresh):

```bash
python3 -m yoke_core.tools.api_server restart
```

## API Reference

All endpoints are prefixed with `/v1/`. All request and response bodies are `application/json`.

### Health Check

```
GET /v1/health
```

Returns service health and API version; any legacy `db_path` token is compatibility-only, and Postgres is authority.

```bash
curl http://localhost:8765/v1/health
```

```json
{
  "status": "ok",
  "version": "v1",
  "db_path": "<legacy-compat-token>"
}
```

### List Items

```
GET /v1/items
```

Returns all backlog items. Supports optional query parameter filters.

| Parameter | Type | Description |
|-----------|------|-------------|
| `project` | string | Filter by project (e.g., `yoke`, `buzz`) |
| `status` | string | Filter by status (e.g., `implementing`, `idea`, `done`) |

Valid statuses (canonical delivery lifecycle, sourced from `packages/yoke-core/src/yoke_core/domain/lifecycle.py`): `idea`, `planned`, `release`, `done`, `cancelled`, `blocked`, `stopped`, `failed`, `refining-idea`, `refined-idea`, `implementing`, `reviewing-implementation`, `reviewed-implementation`, `polishing-implementation`, `implemented`, `planning`, `plan-drafted`, `refining-plan`.

**Canonical-only validation:** Retired status aliases are rejected at the API boundary. Callers must use canonical statuses such as `implementing`, `reviewing-implementation`, `implemented`, `release`, and `done`.

```bash
# All items
curl http://localhost:8765/v1/items

# Filter by status
curl "http://localhost:8765/v1/items?status=implementing"

# Filter by project and status
curl "http://localhost:8765/v1/items?project=yoke&status=implementing"
```

```json
{
  "items": [
    {
      "id": 42,
      "title": "Example item",
      "type": "issue",
      "status": "implementing",
      "priority": "high",
      "flow": "accelerated",
      "rework_count": 0,
      "frozen": false,
      "github_issue": "#123",
      "deployed_to": null,
      "worktree": "YOK-N",
      "project": "yoke",
      "deployment_flow": null,
      "deploy_stage": null,
      "source": "2",
      "created_at": "2026-03-08T03:41:07Z",
      "updated_at": "2026-03-09T14:56:18Z",
      "merged_at": null
    }
  ],
  "count": 1
}
```

Note: `body` is excluded from list responses to keep payload sizes manageable. Use the single-item endpoint to retrieve the body.

Returns `400` with error code `VALIDATION_ERROR` if an invalid status value is provided.

### Get Single Item

```
GET /v1/items/{id}
```

Returns a single item by its numeric ID (the N in YOK-N), including the `body` field.

```bash
curl http://localhost:8765/v1/items/42
```

Returns `404` with error code `NOT_FOUND` if the item does not exist.

### Get Board

```
GET /v1/board
```

Returns items grouped by status columns for a given project.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project` | string | `yoke` | Project whose board to display |

```bash
# Default project (yoke)
curl http://localhost:8765/v1/board

# Specific project
curl "http://localhost:8765/v1/board?project=buzz"
```

```json
{
  "project": "yoke",
  "columns": {
    "idea": [],
    "planning": [],
    "refined": [],
    "implementing": [{"id": 1, "title": "..."}],
    "blocked": [],
    "reviewing": [],
    "implemented": [],
    "release": [],
    "done": [{"id": 2, "title": "..."}]
  },
  "stats": {
    "total": 2,
    "done": 1,
    "active": 1,
    "remaining": 0
  }
}
```

Board columns use the canonical board display order from `packages/yoke-core/src/yoke_core/domain/lifecycle.py` (`STATUS_BOARD_ORDER`). Retired statuses are treated as data bugs and are not normalized at render time.

Returns an empty board (no columns, zero stats) when no items exist for the project.

### Create Item

```
POST /v1/items
```

Creates a new backlog item by invoking `python3 -m yoke_core.api.service_client backlog-cli add` via subprocess. This reuses the same validation and side effects (board rebuild, git commit) as the CLI.

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `title` | string | yes | -- | Non-empty, max 200 characters |
| `type` | string | yes | -- | `epic` or `issue` |
| `priority` | string | no | `medium` | `high`, `medium`, or `low` |

```bash
curl -X POST http://localhost:8765/v1/items \
  -H "Content-Type: application/json" \
  -d '{"title": "New feature idea", "type": "issue", "priority": "high"}'
```

Returns `201` with the full item object on success. Possible error responses:

| Status | Code | Cause |
|--------|------|-------|
| 422 | `VALIDATION_ERROR` | Missing/invalid title, type, or priority |
| 500 | `SUBPROCESS_ERROR` | backlog-cli add failed |
| 503 | `DB_BUSY` | Database locked or subprocess timed out |

### Approve Gate

```
POST /v1/items/{id}/approve
```

Approves a Yoke-handled deployment gate for an item. The item's current
`deploy_stage` must correspond to a `human-approval` stage in its configured
`deployment_flow`.

This endpoint advances the authoritative deployment run state
(`deployment_runs.current_stage`) and the item's mirrored `deploy_stage` to the
next stage in one database transaction, keeps the item at `status=release`, and
records a `DeploymentApprovalGranted` event (non-fatal telemetry). If no active
deployment run exists, it still advances the item's mirrored stage so the
operator can re-run `/yoke usher YOK-N` consistently.

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `comment` | string | no | `null` | Max 500 characters |

```bash
curl -X POST http://localhost:8765/v1/items/42/approve \
  -H "Content-Type: application/json" \
  -d '{"comment": "Reviewed deploy plan, looks good"}'
```

| Status | Code | Cause |
|--------|------|-------|
| 200 | -- | Approved successfully |
| 404 | `NOT_FOUND` | Item does not exist |
| 409 | `INVALID_STATE` | Item is not currently at a `human-approval` stage in its configured flow |
| 422 | `VALIDATION_ERROR` | Comment exceeds 500 characters |
| 503 | `DB_BUSY` | Database locked |

### Configure Capability

```
POST /v1/items/{id}/capability
```

Configures a non-GitHub capability for the project associated with the given item. Uses UPSERT semantics -- creates a new capability (201) or updates an existing one (200) based on the `(project, type)` pair. GitHub uses a verified project binding and control-plane-minted short-lived installation tokens instead.

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `type` | string | yes | Non-empty capability type identifier |
| `config` | object | yes | Non-empty JSON object with capability-specific config |

```bash
curl -X POST http://localhost:8765/v1/items/42/capability \
  -H "Content-Type: application/json" \
  -d '{"type": "ci_workflow_file", "config": {"workflow_file": "ci.yml"}}'
```

| Status | Code | Cause |
|--------|------|-------|
| 201 | -- | New capability created |
| 200 | -- | Existing capability updated |
| 404 | `NOT_FOUND` | Item does not exist |
| 422 | `VALIDATION_ERROR` | Missing/empty type or config |
| 503 | `DB_BUSY` | Database locked |

## Error Response Format

All error responses use a consistent nested envelope:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Item with id 999 not found"
  }
}
```

Error codes: `NOT_FOUND`, `VALIDATION_ERROR`, `INVALID_STATE`, `DB_BUSY`, `SUBPROCESS_ERROR`, `INTERNAL_ERROR`.

## Architecture

The API is a **parallel consumer** of the same connected Postgres authority as the CLI and function-call surfaces.

- **Read endpoints** use the backend connection factory in read-oriented domain helpers.
- **Write endpoints** use the same Postgres authority and surface constraint/connection failures as API errors.
- **`POST /items`** delegates to `python3 -m yoke_core.api.service_client backlog-cli add` via subprocess

No authentication is required for v1 (localhost-only).

### Board Renderer (`runtime/api/board/`)

See `runtime/api/board/README.md` for module-level documentation, CLI usage, and testing instructions.

### Domain Layer

All business logic lives in `runtime/api/domain/`:

| Module | Responsibility |
|--------|---------------|
| `lifecycle.py` | Canonical delivery-item lifecycle: statuses, progression, terminal/exceptional checks |
| `approval.py` | Halt states, approval actions, flow-stage parsing, approval resolution |
| `runs.py` | Deployment-run lookup, status validation, stage advancement |
| `queries.py` | Item filters, frozen semantics, active-queue/pending-work analysis |
| `board.py` | Status-to-bucket mapping, board projection, board stats |

API endpoints delegate to this shared domain layer. SKILL.md flows access the same logic via `python3 -m yoke_core.api.service_client`.

### Service Client

The service client (`python3 -m yoke_core.api.service_client`) is a CLI adapter exposing the Python domain layer to skill flows. Run `python3 -m yoke_core.api.service_client --help` for the current command list.

## Testing

```bash
# Full suite (recommended — uses pyproject.toml testpaths):
python3 -m yoke_core.tools.watch_pytest -- runtime/api/
```

Targeted suites: `test_domain.py` (domain layer), `test_api.py` (endpoints), `test_service_client.py` (CLI adapter), `test_parity.py` (CLI/API agreement). The suites use temporary test databases and mock subprocess calls for write endpoints; no real backlog items are created. Parity tests verify the API and CLI surfaces return identical results for the same logical operations.

## Directory Structure

```
pyproject.toml
runtime/
  api/
    domain/        # Business logic: lifecycle, approval, runs, queries, board
    board/         # Board renderer (art, widgets, zen, sections)
    cli/           # db_router, raw_query
    engines/       # Audit and repair engines
    tools/         # api_server, run_tests, watch_* wrappers
    main.py        # FastAPI application
    service_client.py
    requirements.txt
    README.md
```
