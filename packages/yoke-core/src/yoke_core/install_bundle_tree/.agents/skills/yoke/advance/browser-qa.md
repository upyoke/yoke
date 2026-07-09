# Advance — Browser QA Execution Gate

Called by the advance router when target is `reviewed-implementation`, `implemented`, or `polishing-implementation`. Runs browser scenario orchestrator and screenshot evaluation. Skip if target is not one of those three statuses.

**Context variables** (set by router): `{N}`, `_item_project`, `SCRIPT_DIR`

**This gate is re-entrant:** Retrying the same `/yoke advance YOK-{N} <target>` boundary re-executes the orchestrator. A new passing run satisfies the gate.

---

## Check Unsatisfied Browser Requirements (step 5d.a)

Use the typed `yoke qa gate-summary` surface (function id `qa.gate_summary.run`; works over https) — it shares satisfaction semantics with the verification gate (`yoke_core.domain.qa_gates.check_verification_gate`), so callers do not write raw `qa_requirements` SQL here:

```bash
_qa_target="reviewed-implementation"
[ "{_target}" = "implemented" ] && _qa_target="implemented"
[ "{_target}" = "polishing-implementation" ] && _qa_target="implemented"
_qa_summary_json=$(yoke qa gate-summary --item "YOK-{N}" --target "$_qa_target")
_unsatisfied_browser=$(printf '%s' "$_qa_summary_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['browser_unsatisfied_count'])")
```

If `0`, skip — all blocking browser requirements satisfied. Proceed to finalize.

## Resolve Ephemeral URL (step 5d.b)

The registered `qa.browser_context.get` read returns the branch's latest
recorded preview URL alongside the freshness sha — no raw SQL, works over
https from any project:

```bash
_item_project=$(yoke items get {N} project 2>/dev/null) || true
_eph_url=""
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ]; then
 _ctx_json=$(yoke qa browser-context get --item {N} --project "$_item_project" --expected-branch "YOK-{N}" --json)
 _eph_url=$(printf '%s' "$_ctx_json" | python3 -c "import json,sys; print((json.load(sys.stdin).get('result') or {}).get('ephemeral_url') or '')")
fi
```

Surface URL:
> **Browser QA execution:** Found {count} unsatisfied browser requirement(s). Ephemeral URL: `{_eph_url}`

If empty: warn no URL found.

## Deployment Checks (redeploy-check step–workflow-poll)

Read and follow: `browser-qa-checks.md`

Covers: push branch, "Everything up-to-date" short-circuit, deploy SHA tracking, workflow run polling, env status update after poll, and failed-deploy log retrieval.

## Orchestrator, Evaluation, and Escalation (step 5d.c–5d-eval)

Read and follow: `browser-qa-escalation.md`

Covers: manual screenshot fallback, browser orchestrator invocation, result evaluation, screenshot-evidence completeness gate, visible-defect scan, AC consistency check, and `yoke qa screenshot-evidence satisfy`.

## Artifact Address Resolution

When reviewing screenshots or locating artifact evidence, prefer the browser
orchestrator stdout JSON and the registered QA reads (`yoke qa requirement
list`, `yoke qa requirement get`, and `yoke qa run list`). Each row's typed
`artifact_handle` resolves to its honest address: a filesystem path for
`local`-backend handles (in-session captures live on this machine's disk — the
orchestrator's stdout JSON also lists them), or an `s3://bucket/key` object URI
for uploaded `s3`-backend handles.

There is not yet a registered QA artifact-list wrapper. The DB-router
artifact-list helper is source-dev/admin only; do not teach it as a normal
product-flow recipe.

---

After browser QA passes, return to router for finalize phase.
