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
yoke browser authorize [--project P] [--url URL]
```

`yoke-harness` owns the local daemon/client substrate. The core case runner
executes Browser check and Browser inspection requirements against that same
daemon; screenshot remains diagnostic tooling and records no QA verdict.

## Prerequisites

Network access. Nothing else.

On first use, Yoke copies these packaged sources to the machine runtime,
resolves a Node 18+ toolchain — one already on `PATH`, or a pinned release it
downloads into `~/.yoke/node/<version>/` when the host has none — runs
`npm install` there when dependencies are missing, and installs Chromium when
Playwright cannot find a browser binary. Set `YOKE_BROWSER_AUTOINSTALL=0` to
refuse automatic npm/browser installation and report the missing dependency;
the Node toolchain is resolved before that switch is consulted, because the
daemon cannot start without one.

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
- `src/authorize.js`: plain (non-automated) sign-in window for a project's
  persistent profile
- `src/server.js`: Express HTTP server with bearer auth middleware
- `src/browser-manager.js`: Playwright browser lifecycle
- `src/snapshot.js`: accessibility tree extraction with ref annotation
- `src/screenshot.js`: annotated screenshots
- `src/diff.js`: pixel comparison
- `src/step-runner.js`: browser scenario step execution
- `src/routes/*.js`: snapshot and step execution HTTP routes

The daemon writes `~/.yoke/browser-runtime/.daemon-state.json` with the local
endpoint, PID, bearer token, browser type, health state, and the persistent
profile directory it launched on. The product Python client reads that state
file before sending authenticated daemon requests.

## Persistent Profile

`yoke browser authorize` opens one project's browser profile in a plain window
of this runtime's own Chromium so the operator can sign in once; every context
the daemon later hands out for that project is signed into whatever they signed
into. An agent never completes a sign-in. The window is a directly spawned
browser process rather than a Playwright context, because an
automation-controlled browser is refused by identity providers — Google's
sign-in answers one with "Couldn't sign you in. This browser or app may not be
secure" — and it is this runtime's own binary, launched with the same
cookie-encryption switches Playwright uses, because Chromium drops any stored
cookie it cannot decrypt when it opens a profile. Sites that authenticate with
a session cookie need one more step, which the product client owns: every
session cookie in the profile is given an explicit expiry while no browser
holds it, because a persistent context restores none. The profile lives with
the project's machine-local capability secrets at
`~/.yoke/secrets/capability-secrets/<project>/browser-control/profile`, and a
project with no profile still gets a clean throwaway context. Full contract:
[Persistent Browser Profile](../../../../../docs/browser-substrate/persistent-profile.md).
