# Yoke Browser Automation Runtime

This package is the single source for the Node.js daemon, its focused tests,
and npm manifests. `yoke_harness.browser_runtime_home` materializes it on
demand into `~/.yoke/browser-runtime/`, where `node_modules/`, Playwright
browsers, and daemon state live. Both the harness CLI and core QA execution use
that materializer and source hash; project repositories never receive a
browser source tree.

The product entry points are:

```sh
yoke qa case run --requirement-id N --base-url URL \
  --expected-branch BRANCH --expected-sha SHA
yoke qa browser screenshot URL --output /tmp/capture.png
```

`yoke-harness` owns the local daemon/client substrate. The core case runner
executes Browser check and Browser inspection requirements against that same
daemon; screenshot remains diagnostic tooling and records no QA verdict.

## Prerequisites

- Node.js 18+
- npm

On first use, Yoke copies these packaged sources to the machine runtime,
runs `npm install` there when dependencies are missing, and installs Chromium
when Playwright cannot find a browser binary. Set `YOKE_BROWSER_AUTOINSTALL=0`
to refuse automatic npm/browser installation and report the missing dependency.

## Development Lanes

The product runtime remains on-demand as described above. A source lane that
changes this directory provisions and runs its Node suite from the lane:

```sh
npm ci
npx --no-install playwright install chromium
npm test
```

Run those commands from this directory. The local `node_modules/` tree is
ignored; Chromium uses Playwright's machine cache. The authoritative
`yoke-ci` browser-runtime job runs the same suite only when this directory
changes, including pull-request and merge-queue trees.

## Runtime Files

- `src/daemon.js`: daemon entry point, state file management, idle timer
- `src/server.js`: Express HTTP server with bearer auth middleware
- `src/browser-manager.js`: Playwright browser lifecycle
- `src/snapshot.js`: accessibility tree extraction with ref annotation
- `src/screenshot.js`: annotated screenshots
- `src/diff.js`: pixel comparison
- `src/step-runner.js`: browser scenario step execution
- `src/routes/*.js`: snapshot and step execution HTTP routes

The daemon writes `~/.yoke/browser-runtime/.daemon-state.json` with the local
endpoint, PID, bearer token, browser type, and health state. The product Python
client reads that state file before sending authenticated daemon requests.
