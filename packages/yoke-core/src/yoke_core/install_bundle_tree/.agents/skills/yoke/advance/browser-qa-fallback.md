## Manual Screenshot Fallback

Use this only when `advance/browser-qa.md` step 5d.c fails to link any artifacts.
The goal is to satisfy the reviewed-implementation gate with sanctioned wrappers,
not raw SQL.

For each unsatisfied browser requirement:

### 1. Capture a manual screenshot

```bash
_tmp_screenshot=$(mktemp "${TMPDIR:-/tmp}/yok-{N}-screenshot-{scenario}.XXXXXX.png")
yoke qa browser screenshot "$_eph_url{route}" --output "$_tmp_screenshot"
```

(The launcher token starts the machine-local browser daemon on demand and
works from any project checkout. Operator-debug module form, Yoke
checkout only: `python3 -m yoke_core.domain.browser_client snapshot
screenshot <url> --output <path>`.)

**Guard:** Verify the screenshot file exists and is non-empty before proceeding.
If capture failed, do NOT record a passing run.

```bash
if [ ! -s "$_tmp_screenshot" ]; then
 echo "ERROR: Screenshot capture failed — file missing or empty: $_tmp_screenshot"
 echo "Do NOT record a passing browser_substrate run for this requirement."
 # Skip to the next requirement or stop.
fi
```

### 2. Record the capture run + artifact with registered QA wrappers

Record the run and artifact through dispatcher-backed surfaces. Mint a durable
upload when the project declares an artifacts bucket:

```bash
_run_json=$(yoke qa run add --requirement-id {REQ_ID} \
 --executor-type browser_substrate --qa-kind {REQ_KIND} \
 --execution-status captured \
 --raw-result "Manual screenshot captured — orchestrator fallback" --json)
_run_id=$(printf '%s' "$_run_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['qa_run_id'])")
# Durable path: presign (run `yoke qa artifact presign --help` for flags),
# PUT the file to the returned upload_url, then record the returned
# artifact_handle verbatim:
yoke qa artifact add --requirement-id {REQ_ID} --run-id "$_run_id" \
 --artifact-type screenshot --content-type image/png \
 --artifact-handle "$_handle_json" --metadata '{"source": "manual_fallback"}'
# No bucket declared (qa.artifact.presign answers s3_not_configured)? Record
# an explicit local handle on the capture's absolute path:
#   --artifact-handle "{\"backend\":\"local\",\"path\":\"$_tmp_screenshot\"}"
```

The former one-step DB-router `artifact-path` helper is source-dev/admin only
and is not a normal product flow. Prefer the registered run + artifact calls
above.

### 3. Continue to step 5d-eval

Do not use this fallback to skip browser verification entirely; the screenshots
still need AC review — inspection completes the run via
`yoke qa run complete --requirement-id {REQ_ID} --run-id "$_run_id" --verdict pass|fail`.
