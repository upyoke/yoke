# YOK-959 Investigation Brief for Darius

Date of investigation: March 17, 2026 (YOK-959 conduct timestamps were March 18, 2026 02:22-02:36 UTC, which is March 17, 2026 in New York)

## Executive Summary

During validation of YOK-959, two separate infrastructure failures showed up in the highlighted conduct output:

1. Buzz's standard Playwright E2E command does not currently work as Yoke's "ephemeral URL" E2E path expects.
2. Yoke's browser scenario orchestrator cannot start its local browser daemon on this machine because the `yoke/browser` Node package is not installed, and the wrapper hides the real error.

Neither failure points to a regression in the YOK-959 feature itself. The ephemeral URL was reachable and the feature-specific unit/build checks passed. These are harness/readiness problems.

## Cold-Start Context

### What Yoke expected to do

Yoke's tester contract for external projects says:

- if the conduct has an ephemeral environment URL and an E2E command,
- the tester should run E2E as `BASE_URL={ephemeral_url} {e2e_command}`,
- and browser QA should also run via Yoke's browser substrate for seeded `browser_smoke` and `browser_diff` requirements.

That contract is documented in `/Users/dev/yoke/yoke/docs/agents.md`.

### What Buzz currently exposes

Buzz has two Playwright entry points:

- `npm run test:e2e` -> `npx playwright test --config=e2e/playwright.config.ts`
- `npm run test:smoke` -> `npx playwright test --config=e2e/playwright.smoke.config.ts`

The standard E2E config is local-dev oriented. The smoke config is remote-target oriented.

### What happened in YOK-959

The final validation report for YOK-959 recorded:

- unit tests and build passed,
- E2E could not execute because Playwright tried to start a local Python-backed web server,
- browser scenario execution exited early because the browser daemon could not start.

The review was stored at `review-db.sh get-item 959`, and the browser QA requirements seeded for the item were:

- `qa_requirement` `1344` -> `browser_smoke`
- `qa_requirement` `1345` -> `browser_diff`

Both ended with zero `qa_runs`, which means the browser substrate never got far enough to record evidence.

## Finding 1: Buzz Standard E2E Ignores the Ephemeral-URL Path

### Root cause

Buzz's standard Playwright config hardcodes a local-server harness:

- `use.baseURL = "http://localhost:3000"`
- `webServer[0] = npm run dev`
- `webServer[1] = python -m uvicorn api.main:app --host 0.0.0.0 --port 8000`

File: `/Users/dev/buzz/app/web/e2e/playwright.config.ts`

Because Playwright always evaluates `config.webServer` before tests run, injecting `BASE_URL=https://yok-959.buzzabuzz.com` does not bypass local startup. The harness still tries to boot the local backend and fails before the suite can use the ephemeral URL.

### Why this matters

Yoke's external-project tester path assumes that giving the suite `BASE_URL={ephemeral_url}` is enough to run against the deployed branch. That assumption is false for Buzz's standard E2E command as currently configured.

### Exact reproductions

From `/Users/dev/buzz/.worktrees/YOK-959/app/web`:

```sh
npm run test:e2e
```

Output:

```text
/bin/sh: python: command not found
Error: Process from config.webServer was not able to start. Exit code: 127
```

Also reproduced with the exact Yoke-style env injection:

```sh
BASE_URL=https://yok-959.buzzabuzz.com npm run test:e2e
```

Output was the same:

```text
/bin/sh: python: command not found
Error: Process from config.webServer was not able to start. Exit code: 127
```

This proves the current `BASE_URL` injection path is ineffective for this suite.

### Additional context

- Buzz CI intentionally installs Python and backend dependencies for `frontend-e2e`, which confirms this is not accidental drift in one workstation. See `/Users/dev/buzz/.github/workflows/ci.yml`.
- Yoke's Buzz deviation notes already describe this CI coupling: the E2E job requires Python and backend deps for Playwright webServer startup. See `/Users/dev/yoke/yoke/projects/buzz/DEVIATIONS.md`.
- Buzz's testing docs are now partially stale: they describe E2E as auto-starting `npm run dev`, but the real config also starts a Python API server. See `/Users/dev/buzz/docs/TESTING.md`.

### Important nuance

Most Buzz Playwright specs are not pure "must run on localhost" tests. They use `page.route()` API mocks in `e2e/helpers/api-mocks.ts`, so a remote-target execution mode may be feasible. The blocking issue is the harness, not necessarily the individual tests.

Buzz already has a separate remote-targeting pattern in `e2e/playwright.smoke.config.ts`, which uses `SMOKE_BASE_URL` and does not start local servers. That is evidence the repo already understands the distinction between:

- local mocked E2E
- remote smoke/health validation

The gap is that Yoke's tester is pointed at the local mocked suite, while expecting remote-target behavior.

### Ticket recommendation

Minimum ticket:

- **Buzz: make Playwright E2E usable against Yoke ephemeral URLs**

Suggested scope:

- add a remote-target mode for the standard E2E suite, or a dedicated Yoke-facing command/config,
- if a remote URL env var is present, skip `webServer` startup entirely,
- make the base URL env-driven instead of hardcoded localhost,
- document which suite Yoke should call for ephemeral branch validation.

Suggested acceptance criteria:

- `BASE_URL=https://... npm run test:e2e` either works as a remote-target mode or fails fast with an explicit "unsupported mode" message.
- Remote-target execution does not try to start `npm run dev` or `python -m uvicorn`.
- Yoke has one documented Buzz command it can safely use for ephemeral validation.

Optional follow-up ticket:

- **Buzz: update testing docs to reflect backend webServer coupling and remote-vs-local Playwright modes**

## Finding 2: Yoke Browser Scenario Orchestrator Fails Because Browser Substrate Dependencies Are Missing and the Wrapper Masks It

### Root cause

Yoke's browser scenario path assumes the local browser substrate is already bootstrapped, but that is not verified before use.

The browser daemon wrapper starts the daemon with:

```sh
node "$DAEMON_JS" $_daemon_args >/dev/null 2>&1 &
```

File: `/Users/dev/yoke/.claude/skills/yoke/scripts/browser-daemon.sh`

That means any real startup error is discarded. The caller only gets:

```text
daemon process exited unexpectedly
```

When the daemon was run directly, the real failure was:

```text
Error: Cannot find module 'playwright'
Require stack:
- /Users/dev/yoke/yoke/browser/src/browser-manager.js
- /Users/dev/yoke/yoke/browser/src/daemon.js
```

This happened because `/Users/dev/yoke/yoke/browser/node_modules` does not exist on this machine.

### Exact reproductions

Wrapper repro:

```sh
sh /Users/dev/yoke/.claude/skills/yoke/scripts/browser-daemon.sh start
```

Output:

```text
daemon process exited unexpectedly
```

Direct daemon repro:

```sh
cd /Users/dev/yoke/yoke/browser
node src/daemon.js --state-file /tmp/yoke-browser-investigation-state.json
```

Output:

```text
Error: Cannot find module 'playwright'
```

### Why this matters

`browser-run-scenario.sh` exits with code `2` when daemon startup fails, so conduct/tester only sees a generic prerequisite failure:

- no browser screenshots,
- no browser-diff evidence,
- no `browser_substrate` `qa_runs`,
- no actionable remediation in the error message.

For YOK-959, this is exactly what happened:

```text
1344|browser_smoke|0||
1345|browser_diff|0||
```

So the seeded browser QA requirements existed, but the substrate never produced a run.

### Additional context

Yoke's browser substrate docs explicitly say setup requires:

```sh
cd yoke/browser
npm install
npx playwright install chromium
```

See `/Users/dev/yoke/yoke/docs/browser-substrate.md`.

However:

- `check-prerequisites.sh` does not verify this setup,
- `doctor.sh` does not appear to flag missing browser substrate installs before conduct depends on them,
- `browser-run-scenario.sh` treats missing substrate readiness as a runtime surprise instead of a preflight capability issue,
- `browser-daemon.sh` hides the actual exception.

### Ticket recommendation

Minimum ticket:

- **Yoke: add browser substrate readiness checks and surface real daemon startup errors**

Suggested scope:

- preflight-check that `yoke/browser/node_modules` exists and `playwright` is resolvable,
- preflight-check that Chromium is installed for the substrate,
- make `browser-daemon.sh start` preserve stderr or write to a log file and print the log path on failure,
- ensure conduct/tester/browser-run-scenario report the actual missing dependency instead of opaque exit `2`.

Suggested acceptance criteria:

- missing `playwright` package produces a clear message like `yoke/browser is not bootstrapped: run npm install && npx playwright install chromium`.
- conduct/browser-run-scenario surfaces that message directly.
- a failed daemon start leaves enough diagnostics for cold-start debugging.
- readiness is checkable before running a conduct that depends on browser substrate.

Possible follow-up split if Darius wants smaller tickets:

- **Yoke: doctor/prereq check for browser substrate readiness**
- **Yoke: browser-daemon.sh should not swallow startup stderr**

## Suggested Ticket Split

If Darius wants the smallest practical set, file 2 tickets:

1. Buzz E2E harness does not support Yoke ephemeral URL validation.
2. Yoke browser substrate readiness/diagnostics are missing.

If Darius wants cleaner ownership and tighter scopes, file 3 tickets:

1. Buzz: add/document a remote-target Playwright mode for Yoke's ephemeral validation path.
2. Yoke: add browser substrate readiness checks.
3. Yoke: surface real browser daemon startup errors instead of opaque exit `2`.

## What Is Not the Root Cause

- The ephemeral environment itself was not down. `https://yok-959.buzzabuzz.com` was reachable.
- This was not evidence that YOK-959's playground theme broke application behavior.
- This was not a generic "Playwright flaky" event. Both failures were deterministic and reproducible from source/config.

## Source Files Used in This Investigation

- `/Users/dev/yoke/yoke/docs/agents.md`
- `/Users/dev/buzz/app/web/e2e/playwright.config.ts`
- `/Users/dev/buzz/app/web/e2e/playwright.smoke.config.ts`
- `/Users/dev/buzz/app/web/package.json`
- `/Users/dev/buzz/.github/workflows/ci.yml`
- `/Users/dev/buzz/docs/TESTING.md`
- `/Users/dev/buzz/app/web/e2e/helpers/api-mocks.ts`
- `/Users/dev/yoke/.claude/skills/yoke/scripts/browser-daemon.sh`
- `/Users/dev/yoke/.claude/skills/yoke/scripts/browser-run-scenario.sh`
- `/Users/dev/yoke/yoke/browser/src/daemon.js`
- `/Users/dev/yoke/yoke/browser/src/browser-manager.js`
- `/Users/dev/yoke/yoke/browser/package.json`
- `/Users/dev/yoke/yoke/docs/browser-substrate.md`

## Short Version Darius Can Paste Into a Ticket Description

YOK-959 exposed two infrastructure gaps during validation. First, Buzz's standard Playwright E2E command is still local-harness-only: even when Yoke injects `BASE_URL=https://yok-959.buzzabuzz.com`, Playwright still executes `config.webServer`, tries `python -m uvicorn`, and exits with `/bin/sh: python: command not found` / exit `127`. That means Yoke's current ephemeral-URL E2E contract does not work for Buzz's standard suite. Second, Yoke's browser scenario orchestrator failed before recording any `browser_substrate` evidence because `yoke/browser` is not bootstrapped locally; direct daemon startup shows `Cannot find module 'playwright'`, but `browser-daemon.sh` suppresses stderr and only reports `daemon process exited unexpectedly`. The item's browser QA requirements existed, but both had zero runs recorded. These are reproducible harness/readiness issues, not a YOK-959 product regression.
