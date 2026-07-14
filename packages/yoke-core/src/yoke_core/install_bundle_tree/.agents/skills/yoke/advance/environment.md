# Advance — Ephemeral Environment Orchestration

> **Orchestrator role:** For implementation-entry advances, the advance implementation-entry orchestrator runs the capability-gated environment phase end-to-end and emits `AdvancePhaseCompleted{phase="environment"}`. For projects without the `ephemeral-env` capability the orchestrator emits `outcome=skipped:no-capability` and moves to finalize. For projects whose capability declares `trigger: "flow"` (Yoke core-service previews deploy through the `ephemeral-deploy` flow executor, `yoke_core.domain.deploy_ephemeral`) it emits `outcome=skipped:flow-triggered` — provisioning rows at advance time would create dead pending previews no push workflow deploys. For push-triggered projects (`trigger: "github-push"`, e.g. Buzz), the orchestrator delegates to `yoke_core.engines.advance_implementation_environment.run`, which pushes the branch, creates the `ephemeral_environments` row, derives the preview URL from the capability's `preview_domain`, and stores the deployed SHA in one Python call. Outcomes: `provisioned` (URL + env row + SHA recorded), `skipped:flow-triggered`, `pending:policy-invalid` (malformed `ephemeral-env` settings — repair single keys through the source-dev/admin project capability settings helpers; no registered product CLI wrapper exists yet), `pending:push-failed` (advisory — env row NOT created, retry later). The agent never has to run the recipe below by hand for an implementation-entry advance; this doc remains as the operator reference for non-orchestrator paths and as the contract the orchestrator honors.

Called by the advance router when target is `implementing` and type is not `epic`. Handles ephemeral env setup for browser QA. Skip if target is not `implementing` or type is `epic` (epics use conduct E1-E5).

**Context variables** (set by router/worktree phase): `{N}`, `_type`, `_item_project`, `WORKTREE_PATH`

---

## Capability Gate (step 5b-eph.a)

Check the project's `ephemeral-env` capability through the typed function call. The handler returns a typed result with a boolean `has` field; never wrap a `db_router projects has-capability ... 2>&1` shell choreography for this check.

```json
{
  "function": "projects.capability.has",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "project", "project_id": "{_item_project}"},
  "intent": "advance_eph_capability_check",
  "payload": {"capability": "ephemeral-env"}
}
```

If the response carries `result.has=false`, skip the ephemeral phase. For non-yoke projects, warn:
> Warning: project '{_item_project}' has no ephemeral-env capability — skipping ephemeral environment lifecycle.

## Push Branch to Origin (step 5b-eph.b)

Push branch so ephemeral deploy workflows trigger:
```bash
git -C "$_wt_repo" push -u origin YOK-{N} 2>&1
PUSH_EXIT=$?
```

Non-zero → advisory warning, skip rest of ephemeral orchestration (non-blocking):
> **Advisory:** Branch push failed. Ephemeral environment unavailable.

Success:
> Pushed branch `YOK-{N}` to origin — ephemeral deploy workflow will trigger.

## Create Environment Record (step 5b-eph.c)

```bash
# Internal env-row create (source-dev/admin): create the ephemeral_environments
# row for "$_item_project" and YOK-{N}. No registered product CLI wrapper exists.
```

Empty result → advisory, skip URL derivation.

## Derive Ephemeral URL (step 5b-eph.d RC-A)

Canonical URL derivation formula (must match the internal ephemeral-env helper):
```bash
_branch="YOK-{N}"
_slug=$(printf '%s' "$_branch" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')

# The implementation-entry orchestrator reads the domain from
# sites.settings.domains[0].domain_name via
# yoke_core.engines.advance_implementation_environment. Operator-debug
# paths should inspect that DB setting; do not read project-local flat files.
_ephemeral_url="pending"
```

## Update Environment Record (step 5b-eph.e)

```bash
if [ "$_ephemeral_url" != "pending" ] && [ -n "$_env_id" ]; then
 yoke ephemeral-env update "$_env_id" url "$_ephemeral_url"
fi
```

The env record stays in `pending` status until browser-qa.md discovers the workflow run and transitions it to `starting`. Do NOT set `starting` here — no workflow run has been confirmed yet.

## Store Deployed SHA (step 5b-eph.e2)

Record the initial commit SHA that was pushed. This SHA becomes stale after implementation commits — browser-qa.md handles staleness via "Everything up-to-date" detection after push:
```bash
if [ -n "$_env_id" ]; then
 _deployed_sha=$(git -C "$_wt_repo" rev-parse HEAD 2>/dev/null) || true
 if [ -n "$_deployed_sha" ]; then
 yoke ephemeral-env update "$_env_id" deployed_sha "$_deployed_sha"
 fi
fi
```

## Update Browser QA Requirements (step 5b-eph.f)

If `_ephemeral_url` is derived (not `pending`), call `qa.requirement.update` once per browser-kind requirement on this item. The handler replaces the `localhost:3000` substring in `success_policy` with the ephemeral URL and emits the standard `QaRequirementUpdated` event:

```json
{
  "function": "qa.requirement.update",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "qa_requirement", "qa_requirement_id": <req-id>},
  "intent": "advance_eph_url_rewrite",
  "payload": {
    "success_policy_rewrite": {
      "match": "http://localhost:3000",
      "replace": "${_ephemeral_url}"
    },
    "qa_kinds": ["browser_smoke", "browser_diff"]
  }
}
```

To enumerate the affected `qa_requirement_id`s use the read-only `qa.requirement.list` function with `target.item_id={N}` and filter the result locally — do not compose raw `UPDATE qa_requirements ...` SQL.

## Surface Ephemeral Info (step 5b-eph.g)

If URL derived:
> **Ephemeral environment:** `{_ephemeral_url}` (status: pending)

If pending:
> **Ephemeral environment:** pending (no `domain` key in project config)

---

After environment setup, return to router for finalize phase.
