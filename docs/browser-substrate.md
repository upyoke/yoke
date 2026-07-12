# Browser Automation Substrate

The browser substrate provides a reusable browser capability for interactive browsing, scenario replay, and diff-aware QA. It consists of a Node.js daemon (Playwright), Python client modules, and integration with Yoke's QA artifact pipeline.

The daemon is machine substrate, not repo content: its JS sources ship inside the Python package at `runtime/browser_runtime/` and `yoke_core.domain.browser_runtime_home` materializes them into the machine-level runtime directory `~/.yoke/browser-runtime/`, where npm dependencies, Playwright browsers, and daemon state live. Project repos never receive a browser source tree, `node_modules`, or daemon state.

the `browser-*.sh` launchers (daemon, snapshot, exec, run-scenario, worker) were eliminated in zero-shell wave 3. Invoke the Python modules directly — see the Components table below.

## Related Documentation

- [Browser Scenario Schema](browser-scenario-schema.md) — structured JSON format for `qa_requirements.success_policy` (browser_smoke, browser_diff)

## Architecture

```
+-------------------+ +------------------+ +-------------------+
| Python Clients |---->| Browser Daemon |---->| Playwright |
| (yoke_core.domain) |HTTP | (Node.js/Express)| | (Chromium) |
+-------------------+ +------------------+ +-------------------+
 | |
 v v
+-------------------+ +------------------+
| qa_artifacts | | .daemon-state.json|
| (yoke_core.domain.qa) | | (runtime state) |
+-------------------+ +------------------+
```

### Components

All JS paths below are the packaged sources; the daemon runs from their materialized copy under `~/.yoke/browser-runtime/`.

| Component | Location | Purpose |
|-----------|----------|---------|
| Browser daemon | `runtime/browser_runtime/src/daemon.js` | Node.js process managing Playwright browser lifecycle |
| HTTP server | `runtime/browser_runtime/src/server.js` | Express server with bearer auth, routes for all primitives |
| Browser manager | `runtime/browser_runtime/src/browser-manager.js` | Playwright browser launch, page management, close |
| Snapshot engine | `runtime/browser_runtime/src/snapshot.js` | Accessibility tree extraction with ref annotation |
| Screenshot engine | `runtime/browser_runtime/src/screenshot.js` | Annotated screenshots with numbered ref badges |
| Diff engine | `runtime/browser_runtime/src/diff.js` | Pixel-level image comparison via pixelmatch |
| Step executor | `runtime/browser_runtime/src/step-executor.js` | scenario step execution |
| Snapshot routes | `runtime/browser_runtime/src/routes/snapshot-routes.js` | HTTP routes for snapshot/screenshot/diff |
| Exec routes | `runtime/browser_runtime/src/routes/exec-routes.js` | HTTP routes for step execution |
| `yoke_core.domain.browser_runtime_home` | `runtime/api/domain/browser_runtime_home.py` | Machine runtime dir + hash-gated materialization of the packaged sources |
| `yoke_core.domain.browser_client` | `runtime/api/domain/browser_client.py` | Python daemon client: state, HTTP, lifecycle, exec, snapshot |
| `yoke_core.domain.browser_qa` | `runtime/api/domain/browser_qa.py` | Canonical scenario orchestrator — executes all steps for an item's browser QA requirements |
| `yoke_core.domain.browser_worker` | `runtime/api/domain/browser_worker.py` | Remote browser worker via SSH tunnel |
| `yoke_core.domain.browser_qa_metadata` | `runtime/api/domain/browser_qa_metadata.py` | Validator + negative default for the structured `browser_qa_metadata` item field that replaces classifier inference |

## Daemon Lifecycle

### State File

On startup, the daemon writes `~/.yoke/browser-runtime/.daemon-state.json` (permissions 0600) containing:

```json
{
 "pid": 12345,
 "token": "hex-bearer-token",
 "endpoint": "http://127.0.0.1:9222",
 "browserType": "chromium",
 "startedAt": "2026-01-01T00:00:00.000Z",
 "health": "healthy",
 "port": 9222
}
```

The Python client (`yoke_core.domain.browser_client`) reads this file to discover the daemon endpoint and bearer token.

### Commands

```sh
# Start daemon (headless by default)
python3 -m yoke_core.domain.browser_client daemon start [--port 9222] [--headed] [--idle-timeout 600000]

# Stop daemon (sends /api/stop, then SIGTERM, then SIGKILL)
python3 -m yoke_core.domain.browser_client daemon stop

# Check daemon status (running/crashed/not_running)
python3 -m yoke_core.domain.browser_client daemon status

# Get daemon health JSON from the running process
python3 -m yoke_core.domain.browser_client daemon health
```

### Idle Shutdown

The daemon shuts down after a configurable idle timeout (default 10 minutes) with no API calls. On shutdown, the state file is removed.

### Crash Recovery

If the daemon crashes, the state file remains with a stale PID. On next `start`, the daemon detects the stale PID (via `kill -0`), cleans up the old state file, and launches fresh.

### Security

A bearer token is generated at daemon startup and written to the state file. Every API request must include `Authorization: Bearer {token}`. The state file is owner-readable only (0600).

## Snapshot Primitives

### Accessibility Snapshot

Produces a structured accessibility tree (Playwright's `page.accessibility.snapshot()`) with stable ref IDs on each element.

```sh
python3 -m yoke_core.domain.browser_client snapshot accessibility <url>
```

Output: JSON with `{ tree, refs, url, timestamp }`.

### Annotated Screenshot

Captures a page screenshot with numbered ref badges overlaid on interactive elements.

```sh
python3 -m yoke_core.domain.browser_client snapshot screenshot <url> [--annotate] [--output <path>] [--viewport <WxH>]
```

Output: JSON with `{ imagePath, refs }`. The `refs` map associates integer ref IDs with Playwright locator strings.

### Diff Snapshot

Captures a screenshot and compares it against a baseline image using pixel-level diff (pixelmatch).

```sh
python3 -m yoke_core.domain.browser_client snapshot diff <url> --baseline <path> --viewport <WxH> \
 [--output-dir <dir>] [--threshold <N>]
```

Output: JSON with `{ diff_pct, diff_image_path, candidate_path, baseline_path, viewport }`. When no baseline exists: `{ diff_pct: null, missing_baseline: true, candidate_path }`.

## Ref System

The ref system assigns integer IDs to interactive and semantically significant DOM elements:

- **Ref assignment priority:** `data-testid` > ARIA role+name > semantic CSS selector > positional fallback
- **Stability:** Refs are stable within a single page load (re-running snapshot on the same page produces the same ref assignments)
- **Ref map format:** `{ "1": "role=button[name='Submit']", "2": "#email-input", ... }`
- **Agent usage:** Agents say "click ref 7" or "assert ref 12 is visible" instead of constructing CSS selectors

## Step Executor

Executes a single scenario step.

```sh
python3 -m yoke_core.domain.browser_client exec step '<step-json>' --base-url <url> [--output-dir <dir>]
```

### Supported Actions

| Action | Maps to | Description |
|--------|---------|-------------|
| `navigate` | `page.goto()` | Navigate to a URL (route prepended to base URL) |
| `click` | `locator.click()` | Click an element by selector or ref |
| `fill_form` | `locator.fill()` | Fill a form field |
| `wait_for` | `locator.waitFor()` | Wait for an element to appear |
| `delay` | `page.waitForTimeout()` | Pure time delay (no DOM target required) |
| `assert` | Assertion methods | Assert element state (visible, text content, etc.) |
| `screenshot` | `page.screenshot()` | Capture a screenshot mid-scenario |

### Step Result

```json
{
 "success": true,
 "duration_ms": 250,
 "error": null,
 "artifacts": ["/path/to/screenshot.png"]
}
```

## Scenario Orchestration

`yoke_core.domain.browser_qa` is the canonical orchestrator for executing browser QA scenarios against an ephemeral environment; the agent shape is the tool-shaped launcher token `yoke qa browser run`, which works from any project checkout — every DB leg routes through the `qa.browser_context.get` / `qa.run.add` / `qa.run.complete` / `qa.artifact.add` function ids over both transports. The orchestrator is shared by both the direct advance path (standalone items) and the conduct path (epic items) — there is no parallel implementation. Full details live in [browser-substrate/scenario-orchestration.md](browser-substrate/scenario-orchestration.md):

- **Usage** — launcher shape (`yoke qa browser run --item PREFIX-N [--project P] [--base-url URL]`); module form (`--item-id N`) for checkout dev.
- **What it does** — eight-step run loop (fetches context, resolves base URL, validates reachability, runs steps, records runs/artifacts, emits JSON summary).
- **Exit codes** — `0` pass, `1` fail, `2` prerequisite failure.
- **Re-entrancy and capture-vs-inspection verdict** — captures land with `verdict=NULL`; inspection flips it via `yoke qa run complete`.
- **Executor type enforcement** — only `browser_substrate` runs satisfy the gate for `browser_smoke`/`browser_diff`.
- **Execution paths** — Path 1 (direct advance) and Path 2 (conduct/Tester) both converge on the same orchestrator.
- **Artifact storage convention** — scratch-backed storage with keys like `qa-artifacts/{project}/{item_id}/{run_id}/...`.

## Remote Browser Worker

Runs browser commands on a remote machine via SSH, with a tunnel from local to the remote daemon's HTTP port.

```sh
# Start remote daemon + SSH tunnel
python3 -m yoke_core.domain.browser_worker start <host> [--port 9222] [--local-port 19222]

# Stop tunnel and remote daemon
python3 -m yoke_core.domain.browser_worker stop <host>

# Check tunnel and remote daemon status
python3 -m yoke_core.domain.browser_worker status <host>
```

### Configuration

Remote worker config is stored in `project_capabilities` with `type='remote-browser'`:

```json
{
 "host": "remote.example.com",
 "user": "deploy",
 "key_path": "/path/to/key",
 "browser_path": "/opt/yoke/browser",
 "port": 9222
}
```

### Tunnel Lifecycle

1. Verify remote host is reachable via SSH
2. Start daemon on remote host (`node src/daemon.js`)
3. Create SSH tunnel (`ssh -L localPort:127.0.0.1:remotePort`)
4. Write local state file pointing to `http://127.0.0.1:{localPort}`
5. All `yoke_core.domain.browser_client` snapshot and exec commands work transparently

## QA Artifact Integration

When `--qa-run-id` is provided, browser artifacts are recorded in `qa_artifacts` via `python3 -m yoke_core.cli.db_router qa artifact-add`.

### Flags

All snapshot and exec commands accept these optional flags:

| Flag | Description |
|------|-------------|
| `--qa-run-id N` | QA run ID; triggers artifact recording |
| `--project P` | Project name (e.g., `buzz`) |
| `--route R` | Route path (e.g., `/dashboard`) |
| `--step-index N` | Step index within a scenario |

### Artifact Types

| Type | Content-Type | Produced by |
|------|-------------|-------------|
| `screenshot` | `image/png` | `screenshot`, `diff` (candidate) |
| `diff_image` | `image/png` | `diff` |
| `trace` | `application/json` | `exec step` |
| `baseline` | `image/png` | External baseline capture |
| `log` | `text/plain` | Console log capture |

### Storage Path Convention

When invoked via `yoke_core.domain.browser_client exec` directly (standalone mode with `--qa-run-id`):

```
{project}/test/qa-artifacts/{run_id}/{artifact_type}-{step_index}-{route_slug}.{ext}
```

Example: `buzz/test/qa-artifacts/42/screenshot-3-dashboard.png`

When invoked via `yoke_core.domain.browser_qa` (the canonical orchestrator path):

```
{project}/qa-artifacts/{item_id}/{run_id}/screenshot-{step_index}-{timestamp}.png
```

Example: `buzz/qa-artifacts/941/87/screenshot-0-20260317-143022.png`

Both paths record artifacts to `qa_artifacts` via `yoke qa artifact add`. The orchestrator path organizes by item ID for easier per-item audit trails.

### Metadata

All artifacts include metadata JSON with:

| Field | Required | Description |
|-------|----------|-------------|
| `viewport` | Yes | Viewport dimensions (e.g., `1280x720`) |
| `route` | Yes | Route path (e.g., `/dashboard`) |
| `timestamp` | Yes | ISO 8601 UTC timestamp |
| `project` | Yes | Project name |
| `browser` | Optional | Browser type (default: `chromium`) |
| `step_index` | Optional | Step index within scenario |

### Standalone Mode

Without `--qa-run-id`, artifacts are written to the specified output path without any DB recording. This is the default for interactive debugging.

## Event Catalog

Browser domain events emitted to the `events` table:

| Event Name | Type | Description |
|------------|------|-------------|
| `BrowserDaemonStarted` | `browser_lifecycle` | Daemon started successfully |
| `BrowserDaemonStopped` | `browser_lifecycle` | Daemon stopped (clean or idle) |
| `BrowserSnapshotCaptured` | `browser_action` | Accessibility or annotated snapshot taken |
| `BrowserDiffCompleted` | `browser_action` | Diff comparison completed |
| `BrowserStepExecuted` | `browser_action` | Single scenario step executed |

### Orchestration Events (deferred)

Fine-grained orchestration events (e.g., `BrowserScenarioStarted`, `BrowserScenarioCompleted`, `BrowserScenarioFailed`) are not yet emitted by `yoke_core.domain.browser_qa`. The orchestrator records its results via `qa_runs` and `qa_artifacts` DB tables. Scenario execution is also observable through the underlying `BrowserStepExecuted` events emitted per step by `yoke_core.domain.browser_client exec`. Adding dedicated orchestration events to the `event_registry` is deferred to a follow-up ticket.

## Exit Codes

All shell wrapper scripts use consistent exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Command failed (daemon error, network error, etc.) |
| 2 | Daemon not running |
| 3 | Usage error (bad arguments) |

## Dependencies

The browser substrate's dependencies are **deferred** — none of them are
installed at product install time. They are needed only the first time you run
`yoke qa browser run` (or any other `yoke qa browser` execution), and
`yoke qa browser setup` provisions them on demand at that point.

The deferred set:

- **Node.js 18+** and npm — the one host requirement you supply (the runtime
  Node process); everything below is provisioned for you.
- **Playwright** (`playwright` npm package) with Chromium browser
- **pixelmatch** for image diffing
- **pngjs** for PNG encoding/decoding
- **Express** for the daemon HTTP server

All Node.js dependencies are declared in `runtime/browser_runtime/package.json` and installed into `~/.yoke/browser-runtime/node_modules`. They do not pollute any repo's dependencies.

## Setup

Browser setup is on demand, not at install time. The first `yoke qa browser`
execution provisions everything; `yoke qa browser status` reports readiness
and `yoke qa browser setup` materializes the runtime.

`yoke qa browser setup` materializes the packaged sources into
`~/.yoke/browser-runtime/`, runs `npm install` there when `node_modules` is
missing, and installs Chromium via `npx playwright install chromium` when the
binary is absent. The only host requirement is Node.js 18+ and npm on PATH.

When Node.js or npm is not on PATH, browser execution fails with a readiness
error that points at `yoke qa browser setup` and the platform install hint —
on Linux, Playwright's OS browser libraries may need package-manager access.
Install Node.js 18+ and npm, then run `yoke qa browser setup`. Inspect
readiness any time with `yoke qa browser status`.

## Related

- [Browser Scenario Schema](browser-scenario-schema.md) — structured JSON format for `success_policy` (executor vocabulary, AC-aware generation, refinement)
- `runtime/browser_runtime/README.md` — Quick-start guide and usage examples
- `.agents/skills/yoke/advance/browser-qa.md` — browser execution gate on the `implemented` / `polishing-implementation` path
- `.agents/skills/yoke/advance/implementing/SKILL.md` — AC-aware browser scenario seeding
- `.agents/skills/yoke/conduct/dispatch-context.md` — Tester browser execution dispatch (conduct path)
- `runtime/agents/tester.md` — canonical Tester agent body with Browser Scenario Execution section (generated adapter owned at `runtime/harness/claude/agents/yoke-tester.md`, surfaced via the `.claude/agents` symlink)
