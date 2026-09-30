# Browser Automation Substrate

The browser substrate provides a reusable browser capability for interactive browsing, scenario replay, and diff-aware QA. It consists of a Node.js daemon (Playwright), Python client modules, and integration with Yoke's QA artifact pipeline.

The daemon is machine substrate, not repo content: its JS sources ship inside
`packages/yoke-harness/src/yoke_harness/browser_runtime/`, and
`yoke_harness.browser_runtime_home` materializes them into the
machine-level runtime directory `~/.yoke/browser-runtime/`, where npm
dependencies, Playwright browsers, and daemon state live. Project repos never
receive a browser source tree, `node_modules`, or daemon state.

Invoke the registered `yoke qa` surfaces for QA execution and the Python
modules below for source-development diagnostics.

## Related Documentation

- [Browser Scenario Schema](../.yoke/docs/reference/browser-scenarios.md) —
  immutable `method_config` for `browser-check` and `browser-inspection`
- [Persistent Browser Profile](browser-substrate/persistent-profile.md) — one
  profile per project, signed in once by the operator with
  `yoke browser authorize`
- [Snapshot Primitives](browser-substrate/snapshot-primitives.md) —
  accessibility, screenshot, and diff diagnostics
- [QA Artifact Integration](browser-substrate/qa-artifact-integration.md) —
  how a capture becomes recorded evidence, and where its bytes land

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
| Browser daemon | `packages/yoke-harness/src/yoke_harness/browser_runtime/src/daemon.js` | Node.js process managing Playwright browser lifecycle |
| HTTP server | `packages/yoke-harness/src/yoke_harness/browser_runtime/src/server.js` | Express server with bearer auth, routes for all primitives |
| Browser manager | `packages/yoke-harness/src/yoke_harness/browser_runtime/src/browser-manager.js` | Playwright launch, the interactive page, the pages runs own, close |
| Snapshot engine | `packages/yoke-harness/src/yoke_harness/browser_runtime/src/snapshot.js` | Accessibility tree extraction with ref annotation |
| Screenshot engine | `packages/yoke-harness/src/yoke_harness/browser_runtime/src/screenshot.js` | Annotated screenshots with numbered ref badges |
| Diff engine | `packages/yoke-harness/src/yoke_harness/browser_runtime/src/diff.js` | Pixel-level image comparison via pixelmatch |
| Step runner | `packages/yoke-harness/src/yoke_harness/browser_runtime/src/step-runner.js` | Scenario step execution |
| Snapshot routes | `packages/yoke-harness/src/yoke_harness/browser_runtime/src/routes/snapshot-routes.js` | HTTP routes for snapshot/screenshot/diff |
| Exec routes | `packages/yoke-harness/src/yoke_harness/browser_runtime/src/routes/exec-routes.js` | HTTP routes: open/close the page a run owns, run one step on it |
| `yoke_harness.browser_runtime_home` | `packages/yoke-harness/src/yoke_harness/browser_runtime_home.py` | Single machine-runtime and hash-gated materialization owner |
| `yoke_core.domain.browser_client` | `packages/yoke-core/src/yoke_core/domain/browser_client.py` | Python daemon client: state, HTTP, lifecycle, exec, snapshot |
| `yoke_core.domain.browser_qa` | `packages/yoke-core/src/yoke_core/domain/browser_qa.py` | Internal per-requirement Browser scenario orchestration used by the shared case runner |
| `yoke_core.domain.browser_worker` | `packages/yoke-core/src/yoke_core/domain/browser_worker.py` | Remote browser worker via SSH tunnel |

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
 "port": 9222,
 "profileDir": "/Users/you/.yoke/secrets/capability-secrets/yoke/browser-control/profile"
}
```

`profileDir` is the project's persistent browser profile, empty when the
daemon runs on a throwaway context. A daemon live on a different profile is
restarted rather than reused; see
[Persistent Browser Profile](browser-substrate/persistent-profile.md).

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

A bearer token is generated at daemon startup and written to the state file. Every API request must include `Authorization: Bearer {token}`. The state file is owner-readable only (0600). The persistent profile the daemon may open is owner-only too, and Yoke never reads, stores, or logs a credential the operator typed into it.

## Snapshot Primitives

Accessibility snapshot, annotated screenshot, and pixel diff — their
commands and output shapes live in
[Snapshot Primitives](browser-substrate/snapshot-primitives.md).

## Ref System

The ref system assigns integer IDs to interactive and semantically significant DOM elements:

- **Ref assignment priority:** `data-testid` > ARIA role+name > semantic CSS selector > positional fallback
- **Stability:** Refs are stable within a single page load (re-running snapshot on the same page produces the same ref assignments)
- **Ref map format:** `{ "1": "role=button[name='Submit']", "2": "#email-input", ... }`
- **Agent usage:** Agents say "click ref 7" or "assert ref 12 is visible" instead of constructing CSS selectors

## Step Runner

Executes a single scenario step.

```sh
python3 -m yoke_core.domain.browser_client exec step '<step-json>' --base-url <url> [--output-dir <dir>] [--page-id <id>]
```

### Supported Actions

| Action | Maps to | Description |
|--------|---------|-------------|
| `navigate` | `page.goto()` | Navigate to a URL (route prepended to base URL) |
| `click` | `locator.click()` | Click an element by selector or ref |
| `fill_form` | `locator.fill()` | Fill a form field |
| `wait_for` | `locator.waitFor()` | Wait for an element to appear (first match) |
| `ready` | `locator.waitFor()` / visible text | Wait for a loading placeholder to go away |
| `delay` | `page.waitForTimeout()` | Pure time delay (no DOM target required) |
| `assert` | Assertion methods | Assert element state (visible, text content, etc.) |
| `screenshot` | `page.screenshot()` / `locator.screenshot()` | Capture the page, or one element named by `target` |

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

`yoke qa case run` executes one immutable Browser case and validates deployed
code freshness. Direct Advance and Conduct/Tester share this [runner](browser-substrate/scenario-orchestration.md).

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

The browser client is diagnostic: snapshot commands write to the requested
path and exec returns artifact JSON. It never writes QA records. The
registered case runner is the QA integration boundary — its command, the
artifact types, the storage path convention, and the metadata every artifact
carries live in
[QA Artifact Integration](browser-substrate/qa-artifact-integration.md).

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

Fine-grained orchestration events (e.g., `BrowserScenarioStarted`, `BrowserScenarioCompleted`, `BrowserScenarioFailed`) are not yet emitted by `yoke_core.domain.browser_qa`. The orchestrator records its results via `qa_runs` and `qa_artifacts` DB tables. Scenario execution is also observable through the underlying `BrowserStepExecuted` events emitted per step by `yoke_core.domain.browser_client exec`. Adding dedicated orchestration events to the `event_registry` is deferred to a follow-up work item.

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
installed at product install time. They are needed only the first time a
Browser method executes through `yoke qa case run` (or another `yoke qa
browser` operation), and `yoke qa browser setup` provisions them on demand.

The deferred set:

- **Node.js 18+** and npm — the runtime Node process. Yoke uses one already on
  `PATH`, and provisions a pinned release into `~/.yoke/node/<version>/` when
  the host has none, so a clean machine needs no package manager of its own.
- **Playwright** (`playwright` npm package) with Chromium browser
- **pixelmatch** for image diffing
- **pngjs** for PNG encoding/decoding
- **Express** for the daemon HTTP server

All Node.js dependencies are declared in `packages/yoke-harness/src/yoke_harness/browser_runtime/package.json` and installed into `~/.yoke/browser-runtime/node_modules`. They do not pollute any repo's dependencies.

## Setup

Browser setup is on demand, not at install time: the first `yoke qa browser`
execution provisions everything. QA admission knows that, so a Browser case
needs no `browser-control` project capability row to reach this machine.

`yoke qa browser setup` materializes sources under `~/.yoke/browser-runtime/`,
resolves Node, installs missing npm dependencies and Chromium, and launches a
daemon in a process group independent of the caller's shell. It succeeds only
after the authenticated health endpoint responds; otherwise it names a repair.
Short-lived callers can exit without stopping it; `yoke qa browser status` checks it.

The toolchain resolves cheapest-first: a Node 18+ with npm already on `PATH`,
else the pinned release already unpacked under `~/.yoke/node/<version>/`, else
a checksum-verified download of that release from `nodejs.org/dist`. Every
browser process — the daemon, `npm install`, the Chromium probe, `npx
playwright install`, and the sign-in window — runs against that one resolved
toolchain, with its `bin` directory leading `PATH` so the Node processes
Playwright spawns resolve the same interpreter. Owner:
`yoke_cli.browser_node_toolchain`.

When provisioning cannot proceed, setup exits 2 and names why: the refusal
carries an `error_code` (`node_platform_unsupported`, `node_download_failed`,
`node_archive_digest_mismatch`, `node_archive_unusable`,
`node_provisioned_but_unusable`) and the operator action that clears it, both
in the text message and in the `--json` payload. On Linux, Playwright's OS
browser libraries may still need package-manager access. Inspect readiness any
time with `yoke qa browser status`, which reports the resolved Node version
and whether it came from the host (`host_path`) or from Yoke (`managed`).

## Related

- [Browser Scenario Schema](../.yoke/docs/reference/browser-scenarios.md) —
  `method_config` shape for Browser method cases
- `packages/yoke-harness/src/yoke_harness/browser_runtime/README.md` — Quick-start guide and usage examples
- `.agents/skills/yoke/advance/browser-qa.md` — browser execution gate on the `implemented` / `polishing-implementation` path
- `.agents/skills/yoke/advance/implementing/SKILL.md` — AC-aware browser scenario seeding
- `.agents/skills/yoke/conduct/dispatch-context.md` — Tester browser execution dispatch (conduct path)
- `runtime/agents/tester.md` — canonical Tester agent body with Browser Scenario Execution section (generated adapter owned at `runtime/harness/claude/agents/yoke-tester.md`, surfaced via the `.claude/agents` symlink)
