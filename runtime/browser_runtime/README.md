# Yoke Browser Automation Substrate

Browser daemon and primitives for interactive browsing, scenario replay, and diff-aware QA.

This directory holds the **packaged sources**. The daemon never runs from a repo checkout: `yoke_core.domain.browser_runtime_home` materializes `src/`, `tests/`, and the npm manifests into the machine-level runtime directory `~/.yoke/browser-runtime/`, where `node_modules/`, Playwright browsers, and daemon state live. Project repos never receive a browser source tree.

## Prerequisites

- Node.js 18+
- npm

## Setup

None required. `python3 -m yoke_core.domain.browser_client daemon start` materializes the sources into `~/.yoke/browser-runtime/`, runs `npm install` there when dependencies are missing, and installs Chromium when the binary is absent. To provision manually:

```sh
cd "$(python3 -c 'from yoke_core.domain import browser_runtime_home; print(browser_runtime_home.ensure_materialized())')"
npm install
npx playwright install chromium
```

## Quick Start

The browser runtime no longer uses `browser-*.sh` launchers. Every daemon / snapshot /
exec / worker command is now a Python module. Invoke them directly:

```sh
# 1. Start the daemon
python3 -m yoke_core.domain.browser_client daemon start
# => {"status":"started","endpoint":"http://127.0.0.1:9222","pid":12345}

# 2. Take an accessibility snapshot
python3 -m yoke_core.domain.browser_client snapshot accessibility http://localhost:3000/dashboard
# => {"tree":[...],"refs":{"1":"role=button[name='Submit']",...},"url":"...","timestamp":"..."}

# 3. Take an annotated screenshot
python3 -m yoke_core.domain.browser_client snapshot screenshot http://localhost:3000/dashboard --annotate --output /tmp/dash.png
# => {"imagePath":"/tmp/dash.png","refs":{"1":"role=button[name='Submit']",...}}

# 4. Diff against a baseline
python3 -m yoke_core.domain.browser_client snapshot diff http://localhost:3000/dashboard \
  --baseline /tmp/baseline.png --viewport 1280x720
# => {"diff_pct":0.03,"diff_image_path":"/tmp/diff.png","candidate_path":"/tmp/candidate.png",...}

# 5. Execute a scenario step
python3 -m yoke_core.domain.browser_client exec step '{"action":"navigate","route":"/dashboard"}' \
  --base-url http://localhost:3000
# => {"success":true,"duration_ms":150}

# 6. Stop the daemon
python3 -m yoke_core.domain.browser_client daemon stop
# => stopped
```

## Usage with QA Artifact Recording

When running browser checks as part of a QA run, pass `--qa-run-id` to automatically record artifacts in the `qa_artifacts` table:

```sh
# Screenshot with artifact recording
python3 -m yoke_core.domain.browser_client snapshot screenshot http://localhost:3000/dashboard \
  --annotate \
  --qa-run-id 42 \
  --project external-webapp \
  --route /dashboard
# Artifact recorded: external-webapp/test/qa-artifacts/42/screenshot-dashboard.png

# Diff with artifact recording (records both candidate and diff image)
python3 -m yoke_core.domain.browser_client snapshot diff http://localhost:3000/dashboard \
  --baseline /tmp/baseline.png \
  --viewport 1280x720 \
  --qa-run-id 42 \
  --project external-webapp \
  --route /dashboard
# Two artifacts recorded:
#   external-webapp/test/qa-artifacts/42/screenshot-dashboard.png (candidate)
#   external-webapp/test/qa-artifacts/42/diff_image-dashboard.png (diff)

# Step execution with artifact recording
python3 -m yoke_core.domain.browser_client exec step '{"action":"navigate","route":"/settings"}' \
  --base-url http://localhost:3000 \
  --qa-run-id 42 \
  --project external-webapp \
  --route /settings \
  --step-index 1
# Artifact recorded: external-webapp/test/qa-artifacts/42/trace-1-settings.json
```

Without `--qa-run-id`, no DB writes occur -- artifacts are written to the specified path only.

## Daemon Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port N` | 9222 | HTTP server port |
| `--headed` | (off) | Show browser window (default is headless) |
| `--headless` | (on) | Run without browser window |
| `--idle-timeout N` | 600000 | Idle shutdown timeout in ms (default 10 min) |
| `--state-file path` | `.daemon-state.json` | Path to the daemon state file |

## State File

On startup the daemon writes `~/.yoke/browser-runtime/.daemon-state.json` (0600 permissions) containing:

```json
{
  "pid": 12345,
  "token": "hex-bearer-token",
  "endpoint": "http://127.0.0.1:9222",
  "browserType": "chromium",
  "startedAt": "2024-01-01T00:00:00.000Z",
  "health": "healthy",
  "port": 9222
}
```

The Python client (`yoke_core.domain.browser_client`) reads this file to discover the daemon endpoint and auth token.

## API Routes

All routes require `Authorization: Bearer {token}` header. Responses use:

```json
{ "success": true, "data": { ... } }
{ "success": false, "error": "message" }
```

| Route | Method | Description |
|-------|--------|-------------|
| `/api/health` | POST | Returns health status, uptime, browser connection |
| `/api/stop` | POST | Gracefully shuts down daemon and removes state file |
| `/api/snapshot/accessibility` | POST | Accessibility tree + refs |
| `/api/snapshot/screenshot` | POST | Screenshot capture with optional ref annotations |
| `/api/snapshot/diff` | POST | Diff screenshot against baseline |
| `/api/exec/step` | POST | Execute a single scenario step |

## Remote Worker

Run browser commands on a remote machine via SSH tunnel. The worker entrypoint is
`yoke_core.domain.browser_worker`:

```sh
# Start remote daemon and create tunnel
python3 -m yoke_core.domain.browser_worker start remote.example.com --port 9222 --local-port 19222

# All browser commands now work transparently via tunnel
python3 -m yoke_core.domain.browser_client snapshot screenshot http://localhost:3000/dashboard

# Stop tunnel and remote daemon
python3 -m yoke_core.domain.browser_worker stop remote.example.com
```

Remote config is read from `project_capabilities` (type `remote-browser`).

## Lifecycle

- **Idle shutdown:** After 10 minutes (configurable) of no API calls, the daemon shuts down and removes the state file.
- **Crash recovery:** If the daemon crashes, the state file remains with `health: "crashed"`. On next startup, the daemon detects the stale PID and cleans up.
- **Clean stop:** `POST /api/stop` or `SIGTERM` closes the browser and removes the state file.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Command failed |
| 2 | Daemon not running |
| 3 | Usage error |

## Architecture

- `src/daemon.js` -- CLI entry point, state file management, idle timer, signal handling
- `src/server.js` -- Express HTTP server with bearer auth middleware
- `src/browser-manager.js` -- Playwright browser lifecycle (launch, pages, close)
- `src/snapshot.js` -- Accessibility tree extraction with ref annotation
- `src/screenshot.js` -- Annotated screenshots with numbered ref badges
- `src/diff.js` -- Pixel-level image comparison via pixelmatch
- `src/step-executor.js` -- scenario step execution
- `src/routes/snapshot-routes.js` -- HTTP routes for snapshot/screenshot/diff
- `src/routes/exec-routes.js` -- HTTP routes for step execution

## Tests

```sh
# Node.js unit tests (run from the materialized machine runtime dir)
cd "$(python3 -c 'from yoke_core.domain import browser_runtime_home; print(browser_runtime_home.ensure_materialized())')" && npm test

# Python substrate + worker tests (from a Yoke checkout)
PYTHONPATH=. python3 -m pytest runtime/api/domain/test_browser_client.py \
  runtime/api/domain/test_browser_runtime_home.py \
  runtime/api/domain/test_browser_qa.py \
  runtime/api/domain/test_browser_worker.py \
  runtime/api/domain/test_browser_qa_metadata.py \
  runtime/api/domain/test_browser_qa_scenarios.py
```

## Documentation

- Full substrate docs: `docs/browser-substrate.md`
- Scenario schema: `.yoke/docs/browser-scenario-schema.md`
