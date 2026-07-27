# Yoke Browser Automation Runtime

This package carries the Node.js daemon sources and npm manifests for the
installed Yoke browser QA client. The daemon is materialized on demand into
`~/.yoke/browser-runtime/`, where `node_modules/`, Playwright browsers, and
daemon state live. Project repositories never receive a browser source tree.

The product entry points are:

```sh
yoke qa case run --requirement-id N --base-url URL \
  --expected-branch BRANCH --expected-sha SHA
yoke qa browser screenshot URL --output /tmp/capture.png
```

`yoke-harness` owns the local daemon/client substrate. The shared case runner
executes one materialized Browser check or Browser inspection requirement and
dispatches its DB-backed legs through registered `qa.*` function-call
surfaces. Screenshot is diagnostic tooling and records no QA verdict.

## Prerequisites

- Node.js 18+
- npm

On first use, Yoke copies these packaged sources to the machine runtime,
runs `npm install` there when dependencies are missing, and installs Chromium
when Playwright cannot find a browser binary. Set `YOKE_BROWSER_AUTOINSTALL=0`
to refuse automatic npm/browser installation and report the missing dependency.

## Runtime Files

- `src/daemon.js`: daemon entry point, state file management, idle timer
- `src/server.js`: Express HTTP server with bearer auth middleware
- `src/browser-manager.js`: Playwright browser lifecycle
- `src/snapshot.js`: accessibility tree extraction with ref annotation
- `src/screenshot.js`: annotated screenshots
- `src/diff.js`: pixel comparison
- `src/step-executor.js`: browser scenario step execution
- `src/routes/*.js`: snapshot and step execution HTTP routes

The daemon writes `~/.yoke/browser-runtime/.daemon-state.json` with the local
endpoint, PID, bearer token, browser type, and health state. The product Python
client reads that state file before sending authenticated daemon requests.
