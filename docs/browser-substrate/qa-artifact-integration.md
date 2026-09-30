# QA Artifact Integration

How a diagnostic browser capture becomes recorded QA evidence: which
command owns the run, the artifact types, where bytes land before and
after upload, and the metadata every artifact carries.

Part of the [Browser Automation Substrate](../browser-substrate.md).

The browser client is diagnostic: snapshot commands write to the requested
path and exec returns artifact JSON. It never writes QA records.

The registered case runner is the QA integration boundary:

```sh
yoke qa case run --requirement-id <id> --base-url "<url>" --expected-branch "<branch>" --expected-sha "<sha>"
```

It authorizes the immutable case, executes its steps, completes its QA run,
and records its artifacts. Do not wrap diagnostic calls in parallel records.

### Artifact Types

| Type | Content-Type | Produced by |
|------|-------------|-------------|
| `screenshot` | `image/png` | `screenshot`, `diff` (candidate) |
| `diff_image` | `image/png` | `diff` |
| `trace` | `application/json` | `exec step` |
| `baseline` | `image/png` | External baseline capture |
| `log` | `text/plain` | Console log capture |

### Storage Path Convention

Diagnostic commands write only to caller-supplied `--output` or `--output-dir`
paths; those paths are not QA evidence until the case runner records them.

The case runner first writes captures under project scratch storage:

```
{scratch_root}/{project}/storage/qa-artifacts/{subject}/{run_id}/screenshot-{step_index}-{timestamp}.png
```

Before recording evidence, the runner uploads the file to the configured project
artifact bucket and records this durable key:

```
{artifacts.prefix?}/qa-artifacts/{project}/{subject}/{run_id}/screenshot-{step_index}-{timestamp}.png
```

`{subject}` is the requirement's own owner: its item id or `deployment-run-{run}`.
Only without a bucket does the server copy bytes under `~/.yoke/artifacts/{project}/{subject}/{run_id}/`.
Configured-store failures never downgrade. Hosted `YOKE_QA_ARTIFACT_*` broker settings carry a Platform-derived tenant prefix, never AWS credentials.

### Metadata

All artifacts include metadata JSON with:

| Field | Required | Description |
|-------|----------|-------------|
| `viewport` | Yes | Width and height the page reported when captured |
| `observed_url` | Yes | The url the page was on when captured |
| `route` | Yes | Route the case navigated to (e.g., `/dashboard`) |
| `timestamp` | Yes | ISO 8601 UTC timestamp |
| `project` | Yes | Project name |
| `browser` | Optional | Browser type (default: `chromium`) |
| `step_index` | Optional | Step index within scenario |

### Standalone Mode

Browser-client snapshot and exec commands are interactive diagnostics sharing one named page; they record no run, artifact, or verdict. Use `yoke qa case run` for evidence.
