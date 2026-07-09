# Installer Testing

This guide preserves the Live TUI campaign mechanics for the public installer
and `yoke onboard`. Use it when starting a new installer campaign, extending the
scenario catalog, retaining evidence, or importing campaign results into QA.

For macOS-specific testing, use [INSTALLER-TESTING-MAC.md](INSTALLER-TESTING-MAC.md)
as the sub-guide. The Mac guide covers the reusable physical Mac, visible
Terminal runs, screenshot constraints, Git/Xcode cases, reset procedure, and
the prod local-mode dashboard smoke.

## First Question

Before creating files or running a campaign, ask the operator where retained
evidence should live.

Do not hardcode a personal, machine-local, iCloud, `/tmp`, or worktree path in
the campaign instructions. The operator-provided campaign root is the durable
evidence authority for that run. `/tmp` and remote host staging directories are
scratch only.

Use explicit variables in every command:

```bash
PLAN=.yoke/strategy/INSTALLER-TESTING-PLAN.md
CAMPAIGN_ID=<operator-approved-campaign-id>
CAMPAIGN_ROOT=<operator-approved-absolute-evidence-root>
ENDPOINT=stage
LEDGER="$CAMPAIGN_ROOT/host-ledger.json"
```

Ask for these values at campaign start:

- Retained evidence root and campaign id.
- Endpoint and channel to test, usually `stage` / `latest` or `prod` / `stable`.
- Scenario catalog source. The current catalog is
  `.yoke/strategy/INSTALLER-TESTING-PLAN.md`.
- Host lane: physical Mac, manual SSH host, EC2 fleet, or mixed.
- Token-file paths to stage onto hosts. Never ask for raw token values.
- Cleanup policy for any EC2 resources and local private-key files.
- Whether results should be imported into QA, and the numeric item id or
  epic/task target if so.

## Source Surfaces

The Live TUI campaign helpers are source-checkout tools, not the public product
installer surface:

- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_harness.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_fleet.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_capture.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_runner.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_coordinator.py`
- `packages/yoke-core/src/yoke_core/tools/installer_live_tui_qa_ingest.py`

Related surfaces:

- Public installer entrypoints:
  `packaging/public-installer/install` and
  `packaging/public-installer/install.py`.
- Installer tests and goldens: `tests/installer/`.
- Mac sub-guide: `docs/INSTALLER-TESTING-MAC.md`.
- Public setup docs: `docs/local-setup.md` and
  `docs/onboard-external-project.md`.

## Campaign Layout

Every retained campaign root should use this shape:

```text
<campaign-root>/
  harness-manifest.json
  host-ledger.json
  campaign-plan.json
  assignments/
  recipe-stubs/
  run-specs/
  captures/
  screenshots/
  post-apply/
  raw-host-staging/
  reports/
  summaries/
  logs/
  evidence-archive/
```

Evidence pairing is intentional. A retained screen step should have matching
text and image evidence whenever screenshots are available:

```text
captures/A001/<scenario-id>/000-initial.txt
screenshots/A001/<scenario-id>/000-initial.png
```

If screenshots are blocked, keep the text capture or bridge log and record why
image evidence is absent in the report.

## Scenario Catalog

The current catalog parser reads Markdown tables from a plan file. It recognizes
scenario sections headed `### Wave ...`, then table rows with these columns:

- `id`
- `profile` or `host`
- `flow`
- `assertions`

Scenario ids must look like `NAME-001`: uppercase letters, digits, hyphens, and
a three-digit suffix.

Inspect the catalog:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness catalog \
  --plan "$PLAN" \
  --json
```

If the catalog source is `.yoke/strategy/INSTALLER-TESTING-PLAN.md`, remember it
is a rendered strategy view. When changing that catalog, follow the header in
the file and ingest the update through the strategy surface after editing.

## Render A Campaign

For a simple assignment bundle:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness render-assignments \
  --plan "$PLAN" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --endpoint "$ENDPOINT" \
  --assignment-size 5 \
  --json
```

For a coordinator-managed campaign, render the manifest, assignments, host
demand, and recipe stubs:

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator plan-campaign \
  --plan "$PLAN" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --endpoint "$ENDPOINT" \
  --assignment-size 5 \
  --slots-per-host 1 \
  --json
```

Use `--max-scenarios N` for a small proof run. Use `--include-mac` only when the
physical Mac lane is intentionally part of the campaign plan.

## Prepare Hosts

For EC2 host work, preview first:

```bash
python3 -m yoke_core.tools.installer_live_tui_fleet fleet-plan \
  --campaign-id "$CAMPAIGN_ID" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --count 1 \
  --profile prepared-git \
  --endpoint "$ENDPOINT" \
  --json
```

Create hosts only after operator approval:

```bash
python3 -m yoke_core.tools.installer_live_tui_fleet fleet-prepare \
  --campaign-id "$CAMPAIGN_ID" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --count 1 \
  --profile prepared-git \
  --endpoint "$ENDPOINT" \
  --yoke-token-file <local-yoke-token-file> \
  --github-token-file <local-github-token-file> \
  --github-repo <owner/repo> \
  --execute \
  --json
```

`fleet-prepare` writes `host-ledger.json` under `CAMPAIGN_ROOT`. If a campaign
needs multiple independently prepared fleets, preserve each returned ledger path
before running another prepare command that could replace the root ledger.

Reset a ledgered host before reusing it:

```bash
python3 -m yoke_core.tools.installer_live_tui_fleet fleet-reset \
  --ledger "$LEDGER" \
  --target-profile bare-no-uv \
  --execute \
  --json
```

## Compile And Run Specs

The coordinator can seed known recipe stubs, compile ready recipes into
run-spec JSON, and execute them.

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator seed-recipes \
  --campaign-root "$CAMPAIGN_ROOT" \
  --endpoint "$ENDPOINT" \
  --json
```

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator compile-recipes \
  --campaign-root "$CAMPAIGN_ROOT" \
  --runs-per-spec 1 \
  --json
```

Run one compiled spec after reviewing it:

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator run-batch \
  --spec "$CAMPAIGN_ROOT/run-specs/run-spec-001.json" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --ledger "$LEDGER" \
  --execute \
  --json
```

Run multiple specs with a concurrency cap:

```bash
python3 -m yoke_core.tools.installer_live_tui_coordinator run-waves \
  --spec-dir "$CAMPAIGN_ROOT/run-specs" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --ledger "$LEDGER" \
  --max-parallel 4 \
  --execute \
  --json
```

For long runs, capture command output to a log file under
`$CAMPAIGN_ROOT/logs/` and inspect that captured file on failure. Do not stream
secrets or token file contents.

## Manual Capture

Use capture helpers for live tmux panes when a scenario is driven manually or
semi-manually.

Capture a local tmux pane:

```bash
python3 -m yoke_core.tools.installer_live_tui_capture capture \
  --campaign-root "$CAMPAIGN_ROOT" \
  --assignment-id A001 \
  --scenario-id <scenario-id> \
  --step 000-initial \
  --json
```

Capture a ledgered SSH host's tmux pane:

```bash
python3 -m yoke_core.tools.installer_live_tui_capture ssh-capture \
  --campaign-root "$CAMPAIGN_ROOT" \
  --assignment-id A001 \
  --scenario-id <scenario-id> \
  --step 000-initial \
  --ledger "$LEDGER" \
  --json
```

Send small key transitions:

```bash
python3 -m yoke_core.tools.installer_live_tui_capture ssh-send-keys \
  --ledger "$LEDGER" \
  Enter \
  --json
```

Backfill image evidence from an already retained text capture:

```bash
python3 -m yoke_core.tools.installer_live_tui_capture file-capture \
  --campaign-root "$CAMPAIGN_ROOT" \
  --assignment-id A001 \
  --scenario-id <scenario-id> \
  --step 010-after-enter \
  --source "$CAMPAIGN_ROOT/captures/A001/<scenario-id>/010-after-enter.txt" \
  --json
```

## Direct Scenario Runner

For one ledgered SSH scenario, use `run-ssh`. This starts the command, performs
capture/action steps, records expectations and post-checks, and writes a report.

```bash
python3 -m yoke_core.tools.installer_live_tui_runner run-ssh \
  --ledger "$LEDGER" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --assignment-id A001 \
  --scenario-id <scenario-id> \
  --command 'curl -fsSL https://api.stage.upyoke.com/install | bash' \
  --action 000-initial \
  --action 010-after-enter:Enter \
  --expect 'Yoke' \
  --post-check 'command -v yoke' \
  --post-check 'find "$HOME/.yoke/onboarding-runs" -maxdepth 3 -type f -name "*.json" -print' \
  --execution-mode tmux \
  --json
```

Use `--stage-file LOCAL=REMOTE` and `--stage-url URL=REMOTE` to stage token
files, fixtures, or installer scripts without printing their contents.

## Reports And Validation

Each assignment report belongs under:

```text
reports/A001.json
```

Minimum report content:

- Assignment id, host id, profile, endpoint, start and finish time.
- Scenario ids and pass/fail result per scenario.
- Paths to retained captures, screenshots, post-apply checks, and raw staging.
- Observed screen titles or key assertions.
- Failure kind, last capture, last screenshot, and repro keys when failing.
- Secret-scan result.

Validate one report:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness validate-report \
  --report "$CAMPAIGN_ROOT/reports/A001.json" \
  --campaign-root "$CAMPAIGN_ROOT" \
  --json
```

Scan retained evidence for obvious secret markers:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness secret-scan \
  "$CAMPAIGN_ROOT/captures" \
  "$CAMPAIGN_ROOT/screenshots" \
  "$CAMPAIGN_ROOT/logs" \
  "$CAMPAIGN_ROOT/post-apply" \
  "$CAMPAIGN_ROOT/raw-host-staging" \
  --json
```

Collect the whole campaign:

```bash
python3 -m yoke_core.tools.installer_live_tui_harness collect-reports \
  --campaign-root "$CAMPAIGN_ROOT" \
  --json
```

A retained campaign is not green until `collect-reports` reports no evidence
issues and the secret scan is clean.

## QA Import

When campaign evidence belongs to a concrete QA gate, import it after the
campaign collector is green. Use bare numeric item ids.

Preview:

```bash
python3 -m yoke_core.tools.installer_live_tui_qa_ingest \
  --campaign-root "$CAMPAIGN_ROOT" \
  --item-id <numeric-item-id> \
  --json
```

Write QA rows:

```bash
python3 -m yoke_core.tools.installer_live_tui_qa_ingest \
  --campaign-root "$CAMPAIGN_ROOT" \
  --item-id <numeric-item-id> \
  --execute \
  --json
```

For epic task evidence, use `--epic-id <numeric-epic-id> --task-num <number>`.
For deployment-run evidence, use `--deployment-run-id <run-id>`.

## Mac Lane

The Mac lane is a serial physical-host lane. Do not fold it into an EC2 fleet
run. Use [INSTALLER-TESTING-MAC.md](INSTALLER-TESTING-MAC.md) for:

- Host access and token-file placement.
- Visible Terminal and packaged PTY bridge operation.
- Screenshot and Screen Recording gotchas.
- Git/Xcode recovery cases.
- Reset and verification commands.
- Stage/prod-on-one-machine behavior.

Mac evidence should still be copied into the operator-approved campaign root and
validated by the same `secret-scan`, `validate-report`, and `collect-reports`
commands where practical.

## Cleanup

Clean up EC2 resources with the ledger that created them:

```bash
python3 -m yoke_core.tools.installer_live_tui_fleet fleet-cleanup \
  --ledger "$LEDGER" \
  --execute \
  --json
```

Use `--keep-key-file` only when the operator explicitly wants to retain the
generated private key file for later host access.

Archive superseded evidence by moving it under:

```text
<campaign-root>/evidence-archive/<timestamp-or-reason>/
```

Do not delete retained evidence unless the operator explicitly says it is
scratch or duplicate material.

## Closeout Checklist

Before calling a campaign complete:

- Campaign root was chosen by the operator and recorded in the summary.
- Endpoint, channel, source commit/version, and public installer URL were
  recorded.
- Every scenario has a report row with pass, fail, or blocked.
- Every pass has retained evidence and post-apply truth checks.
- Secret scan is clean.
- `collect-reports` is green or remaining issues are explicitly explained.
- Confirmed product bugs have scenario ids, host profile, endpoint version,
  capture path, screenshot path if available, repro keys, and expected vs
  observed behavior.
- EC2 resources are cleaned up or intentionally retained with operator approval.
- QA import is complete when the campaign is tied to a QA gate.
