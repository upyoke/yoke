# Browser QA Scenarios — Design Specification

> **Ticket:** YOK-834
> **Status:** Design specification
> **Depends on:** YOK-833 (QA platform, landed), YOK-831 (delivery runtime, landed)
> **Consumed by:** YOK-846 (auto-attachment policy), YOK-850 (hostname-based URLs)

This document codifies the scenario-driven browser QA model for Yoke: how
browser checks are authored, structured, targeted, executed, and promoted. It
builds on the live QA platform (YOK-833) and delivery runtime (YOK-831) without
redesigning either.

---

## 1. Scenario JSON Schema

A browser QA scenario is a structured definition stored in a `qa_requirements`
row. The scenario definition lives in the `success_policy` JSON field, extended
with scenario-specific structure. No new tables are required.

### 1.1 Scenario Shape

Every browser scenario requirement uses `success_policy` with a top-level
`scenario` object:

```json
{
  "type": "scenario",
  "scenario": {
    "narrative": "User logs in, sees dashboard with recent activity",
    "preconditions": [
      "User account exists with email test@example.com",
      "At least one activity record exists in the database"
    ],
    "steps": [
      {"route": "/login", "action": "fill_form", "fields": {"email": "test@example.com", "password": "test123"}},
      {"route": "/login", "action": "click", "target": "button[type=submit]"},
      {"route": "/dashboard", "action": "wait_for", "target": ".activity-list"},
      {"route": "/dashboard", "action": "assert", "check": "visible", "target": ".activity-item", "min_count": 1}
    ],
    "check_style": "deterministic",
    "viewport": {"width": 1280, "height": 720}
  },
  "criteria": "All steps complete without error; activity list is visible with at least one item"
}
```

### 1.2 Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | yes | Always `"scenario"` for browser QA scenarios |
| `scenario.narrative` | string | yes | User-facing description of what the scenario validates. Reads like a stakeholder outcome. |
| `scenario.preconditions` | string[] | no | Setup steps required before execution (seed data, auth state, feature flags). |
| `scenario.steps` | object[] | yes | Ordered sequence of route/action targets (see Step Schema below). |
| `scenario.check_style` | string | yes | One of `deterministic`, `diff_aware`, `agent_judged` (see Section 4). |
| `scenario.viewport` | object | no | `{width, height}` in pixels. Defaults to `{1280, 720}`. |
| `scenario.baseline_ref` | string | no | For `diff_aware` style: reference to baseline image set (see Section 5). |
| `scenario.confidence_pass` | number | no | For `agent_judged` style: minimum confidence to pass (0.0-1.0). Default: 0.8. |
| `scenario.confidence_fail` | number | no | For `agent_judged` style: maximum confidence to fail (0.0-1.0). Default: 0.4. |
| `criteria` | string | yes | Human-readable success criteria. Equivalent to `success_policy` criteria in non-scenario requirements. |

### 1.3 Step Schema

Each step in `scenario.steps` describes a single action:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `route` | string | yes | Relative URL path (e.g., `/dashboard`, `/settings/billing`). Never absolute — base URL injected at runtime. |
| `action` | string | yes | One of: `navigate`, `click`, `fill_form`, `wait_for`, `assert`, `screenshot`, `scroll`, `hover`, `type`, `select` |
| `target` | string | no | CSS selector for the action target. Required for `click`, `fill_form`, `wait_for`, `assert`, `hover`, `type`, `select`. |
| `fields` | object | no | Key-value pairs for `fill_form` action. Keys are field selectors or names. |
| `check` | string | no | For `assert` action: `visible`, `hidden`, `text_contains`, `text_equals`, `attr_equals`, `count_gte`, `count_eq`, `http_status`, `computed_style` |
| `expected` | any | no | Expected value for assertion checks. |
| `min_count` | number | no | For `count_gte` checks: minimum element count. |
| `timeout_ms` | number | no | Override default wait timeout for this step. Default: 5000. |
| `capture` | boolean | no | If true, capture a screenshot after this step (appended to `qa_artifacts`). Default: false for deterministic, true for agent_judged. |

### 1.4 Mapping to qa_requirements Columns

| qa_requirements column | Value for scenario requirements |
|---|---|
| `qa_kind` | `e2e`, `smoke`, or `visual-regression` (existing kinds — no new values needed) |
| `qa_phase` | `verification` (item-scoped) or `post_deploy` (deployment-run-scoped) |
| `target_env` | Resolved by environment selection rules (Section 3) |
| `blocking_mode` | `blocking` (default for validation) or `non_blocking` (monitoring) |
| `requirement_source` | `ac_derived` (Tester-generated), `flow_derived` (deployment default), `explicit` (operator-added) |
| `success_policy` | The scenario JSON above |
| `capability_requirements` | `["browser"]` — indicates browser executor needed |
| `suite_id` | Set when a scenario is promoted to a durable suite (Section 8) |

### 1.5 Executor Agnosticism (AC-21)

The scenario schema describes **what** to check, not **how** to run it. The
executor interprets the schema:

| Executor type | How it consumes the scenario |
|---|---|
| `playwright` | Maps steps to Playwright API calls (`page.goto`, `page.click`, `page.fill`, `locator.waitFor`) |
| `shell` | Maps steps to curl/wget + HTML parsing (limited — assertion-only scenarios) |
| `agent` | Tester agent reads steps as instructions, executes via browser tool, judges screenshots |
| `remote-browser` | Sends scenario to a remote browser worker service, receives screenshots and results |

The `executor_type` on `qa_runs` records which executor actually ran the
scenario. The same `qa_requirements` row can be executed by different executors
across different runs.

---

## 2. Success Policies Per Check Style (AC-2)

Success policies are codified per requirement in the `success_policy` JSON
field. The scenario model introduces a new top-level `type: "scenario"` that
wraps the existing policy types with scenario-specific structure.

### 2.1 Deterministic Scenarios

```json
{
  "type": "scenario",
  "scenario": {
    "narrative": "Login page renders correctly and accepts valid credentials",
    "steps": [
      {"route": "/login", "action": "assert", "check": "visible", "target": "#email-input"},
      {"route": "/login", "action": "assert", "check": "visible", "target": "#password-input"},
      {"route": "/login", "action": "fill_form", "fields": {"#email-input": "test@example.com", "#password-input": "test123"}},
      {"route": "/login", "action": "click", "target": "button[type=submit]"},
      {"route": "/dashboard", "action": "wait_for", "target": ".user-greeting"}
    ],
    "check_style": "deterministic"
  },
  "criteria": "All selectors visible, form submission redirects to dashboard with greeting"
}
```

Pass condition: every step completes without error or timeout.

### 2.2 Diff-Aware Scenarios

```json
{
  "type": "scenario",
  "scenario": {
    "narrative": "Dashboard layout matches baseline after feature change",
    "steps": [
      {"route": "/dashboard", "action": "wait_for", "target": ".dashboard-loaded"},
      {"route": "/dashboard", "action": "screenshot", "capture": true}
    ],
    "check_style": "diff_aware",
    "baseline_ref": "dashboard-main-1280x720",
    "viewport": {"width": 1280, "height": 720}
  },
  "criteria": "Visual diff from baseline is within 5% threshold",
  "diff_threshold_pct": 5.0
}
```

Pass condition: pixel diff percentage between captured screenshot and baseline
is within `diff_threshold_pct`.

### 2.3 Agent-Judged Scenarios

```json
{
  "type": "scenario",
  "scenario": {
    "narrative": "Settings page is visually coherent and all form elements are properly styled",
    "steps": [
      {"route": "/settings", "action": "wait_for", "target": "form"},
      {"route": "/settings", "action": "screenshot", "capture": true},
      {"route": "/settings/billing", "action": "wait_for", "target": ".billing-section"},
      {"route": "/settings/billing", "action": "screenshot", "capture": true}
    ],
    "check_style": "agent_judged",
    "confidence_pass": 0.8,
    "confidence_fail": 0.4
  },
  "criteria": "Settings and billing pages are visually coherent, properly styled, no broken layouts or missing elements"
}
```

Pass condition: agent confidence score >= `confidence_pass`. Fail if <=
`confidence_fail`. Between thresholds: `inconclusive` (may retry).

---

## 3. Environment Selection Rules (AC-4, AC-5)

### 3.1 Decision Table

Given an item's `project`, `qa_phase`, and available environments, resolve the
`target_env` for a browser scenario:

| qa_phase | Project has ephemeral capability? | Project has preview envs? | Resolved target_env | Rationale |
|---|---|---|---|---|
| `verification` | yes | — | `ephemeral` | Branch-isolated, realistic deploy state |
| `verification` | no | yes | `preview` | Shared non-prod target, next best option |
| `verification` | no | no | `local` | Localhost fallback when no deploy target available |
| `post_deploy` | — | yes (target stage) | `preview` | Release validation on named non-prod target |
| `post_deploy` | — | no (targeting prod) | `prod` | Post-deploy smoke on production |
| `manual_acceptance` | — | yes | `preview` | Human review on deployed non-prod |
| `manual_acceptance` | — | no | `prod` | Human review on production |

### 3.2 Override Rules

- **Operator override:** The operator can set `target_env` explicitly on any
  `qa_requirements` row. Explicit values are never overridden by the decision
  table.
- **Flow-level default:** A `deployment_flow` may specify a `target_env` on the
  flow or on individual stages. Flow-derived requirements inherit this.
- **Project-level default:** A project may declare a default `target_env` for
  verification-phase browser QA in its `project_capabilities` config.

Priority: explicit requirement > flow stage > flow default > project default > decision table.

### 3.3 Base-URL Injection (AC-4)

Scenario steps use relative routes (`/login`, `/dashboard`). The executor
resolves the full URL at runtime by prepending the environment's base URL:

| target_env | Base URL source |
|---|---|
| `local` | `http://localhost:{port}` from project config or `test_command_e2e` output |
| `ephemeral` | `url` column from `ephemeral_environments` table, queried by `(project, branch)` |
| `preview` | `url` column from `deployment_preview_environments` table, queried by `(project, env_name)` |
| `prod` | Project's production URL from `project_capabilities` config (`type=production-url`) |

The base URL is injected into the executor context, never hardcoded in the
scenario definition. If the resolved URL is empty or the environment is
unavailable, the executor must fail with a clear error rather than silently
skipping.

---

## 4. Browser Check Styles (AC-11)

Three styles of browser checking, each producing different evidence and using
different success evaluation:

### 4.1 Deterministic Assertions

- **What:** Selector visibility, computed style values, HTTP status codes,
  element counts, text content.
- **Evidence:** Step-by-step pass/fail log. Optional screenshots on failure.
- **Evaluation:** Binary — all assertions pass or the scenario fails.
- **Executor affinity:** `playwright` (native assertions), `shell` (curl + HTML
  parsing for HTTP checks).
- **success_policy shape:** `{"type": "scenario", "scenario": {"check_style": "deterministic", ...}, "criteria": "..."}`

### 4.2 Diff-Aware Visual Comparison

- **What:** Pixel-level comparison of current screenshot against a stored
  baseline image.
- **Evidence:** Current screenshot, baseline image, diff image highlighting
  changes, diff percentage.
- **Evaluation:** Diff percentage within `diff_threshold_pct` threshold.
- **Executor affinity:** `playwright` (screenshot capture) + image comparison
  library; `remote-browser` (screenshot service).
- **success_policy shape:** `{"type": "scenario", "scenario": {"check_style": "diff_aware", "baseline_ref": "...", ...}, "criteria": "...", "diff_threshold_pct": 5.0}`

### 4.3 Agent-Judged Visual Acceptance

- **What:** LLM-based assessment of screenshots against the scenario narrative
  and criteria.
- **Evidence:** Screenshots, agent confidence score, agent reasoning text.
- **Evaluation:** Confidence >= `confidence_pass` (pass), <=
  `confidence_fail` (fail), between (inconclusive — retry or escalate).
- **Executor affinity:** `agent` (Tester agent reads screenshots, provides
  judgment).
- **success_policy shape:** `{"type": "scenario", "scenario": {"check_style": "agent_judged", "confidence_pass": 0.8, "confidence_fail": 0.4, ...}, "criteria": "..."}`

### 4.4 Combining Styles

A single scenario uses one `check_style`. When an item needs multiple styles
(e.g., deterministic login flow + visual acceptance of the dashboard), create
separate `qa_requirements` rows — one per scenario. This matches the existing
QA platform model (one requirement = one check).

---

## 5. Baseline Selection Rules for Diff-Aware Checks (AC-20)

### 5.1 Baseline Identity

A baseline is identified by a composite key:

```
{project}/{route_slug}/{viewport_width}x{viewport_height}
```

Example: `buzz/dashboard-1280x720`, `buzz/settings-billing-1920x1080`.

The `route_slug` is derived from the route by replacing `/` with `-` and
stripping leading `-`. Example: `/settings/billing` → `settings-billing`.

### 5.2 Baseline Storage

Baselines are stored as `qa_artifacts` with `artifact_type = "baseline"`:

| qa_artifacts column | Value |
|---|---|
| `artifact_type` | `baseline` |
| `content_type` | `image/png` |
| `storage_path` | `{project_repo}/test/baselines/{route_slug}-{width}x{height}.png` |
| `metadata` | `{"route": "/dashboard", "viewport": {"width": 1280, "height": 720}, "captured_at": "2026-03-16T...", "branch": "main", "commit": "abc123"}` |

Baselines are versioned in the project repository under `test/baselines/`. This
ensures baselines evolve with the code and are reviewable in PRs.

### 5.3 Baseline Lifecycle

1. **Capture:** When a diff-aware scenario runs against `main` (or the project's
   default branch) and passes, the captured screenshot becomes a candidate
   baseline.
2. **Update:** Baselines are updated explicitly by running the scenario with a
   `--update-baseline` flag (operator action). Never auto-updated on pass.
3. **Review:** Baseline updates appear as file changes in PRs, visible to
   reviewers.
4. **Selection:** At execution time, the executor looks up `baseline_ref` in the
   scenario, resolves to the file path, and loads the image for comparison.

### 5.4 Missing Baselines

If a diff-aware scenario references a `baseline_ref` that does not exist on
disk, the executor must:
1. Capture the current screenshot.
2. Record a `qa_runs` entry with `verdict = "inconclusive"` and
   `raw_result` explaining the missing baseline.
3. Store the captured screenshot as a candidate baseline artifact.
4. The scenario does NOT pass (missing baseline is not a pass condition).

---

## 6. Browser Artifact Normalization (AC-3)

### 6.1 Artifact Types

Browser scenario executions produce artifacts stored in `qa_artifacts`:

| artifact_type | content_type | Description |
|---|---|---|
| `screenshot` | `image/png` | Page screenshot at a specific step |
| `diff_image` | `image/png` | Visual diff overlay (diff-aware checks) |
| `baseline` | `image/png` | Known-good reference image |
| `trace` | `application/zip` | Playwright trace archive |
| `video` | `video/webm` | Screen recording of scenario execution |
| `log` | `text/plain` | Console log, network log, or error output |

### 6.2 Required Metadata

All browser artifacts must include these metadata fields in the `metadata` JSON:

| Field | Type | Required | Description |
|---|---|------|-------------|
| `viewport` | object | yes | `{width, height}` at capture time |
| `route` | string | yes | Relative route at capture time |
| `step_index` | number | no | Index into scenario steps array |
| `timestamp` | string | yes | ISO 8601 capture timestamp |
| `browser` | string | no | Browser name/version (e.g., `chromium-120`) |
| `project` | string | yes | Project identifier |

### 6.3 Storage Convention

Artifacts are stored under the project's test output directory:

```
{project_repo}/test/qa-artifacts/{run_id}/{artifact_type}-{step_index}-{route_slug}.{ext}
```

The `storage_path` in `qa_artifacts` records the absolute path. Artifacts from
ephemeral runs are not committed to the repo — they persist only as long as the
QA run is relevant. Artifacts from durable suite runs may be committed if the
project's test infrastructure supports it.

---

## 7. Preview vs Ephemeral Environment Contracts (AC-6, AC-7, AC-8, AC-9, AC-10)

### 7.1 Definitions

| Aspect | Preview | Ephemeral |
|---|---|---|
| **Identity** | Named, project-scoped (e.g., `staging`, `shmaging`) | Branch-scoped, item-scoped (e.g., `YOK-42`) |
| **Lifecycle** | Long-lived (days to permanent) | Short-lived (hours to single session) |
| **Table** | `deployment_preview_environments` | `ephemeral_environments` |
| **Status model** | `available` ↔ `claimed` → `available` | `starting` → `healthy`/`failed` → `stopped` |
| **Owner** | Deployment-run orchestration (Usher) | Validation-time orchestration (Conduct) |
| **Creation trigger** | Operator request or flow stage | Branch push, PR creation, or conduct dispatch |
| **URL resolution** | `(project, env_name)` lookup | `(project, branch)` lookup |

### 7.2 Preview Environment Contract (AC-7, AC-9)

**Creation:**
- Operator requests a named preview via Usher or deployment flow stage.
- The project pattern (template/capability) defines how Yoke provisions the
  preview (CDK deploy, Docker compose, VPS provisioning, etc.).
- If the requested `env_name` already exists in
  `deployment_preview_environments`, the system must check occupancy via
  `check-preview-occupancy` and require explicit operator choice:
  - **create-new:** Create a new preview with a different name.
  - **overwrite:** Claim the existing preview for this run (emits
    `PreviewEnvOverwritten` event).
  - **abort:** Cancel the operation.
- This conflict detection is already live via `check-preview-occupancy` and
  `claim-preview` operations in `yoke-db.sh runs`.

**Discovery:**
- Preview URLs are resolved by `(project, env_name)` query on
  `deployment_preview_environments`.
- For browser scenarios targeting a preview, the executor resolves the base URL
  from the preview's `url` column.

**Cleanup (AC-10):**
- `shared` preview environments (e.g., `staging`) are **never auto-destroyed**.
  Only explicit operator teardown.
- `adhoc` preview environments are eligible for automatic cleanup only after the
  associated release has completed successfully in its final target environment.
- This is already enforced by `can-cleanup-preview` in `yoke-db.sh runs`,
  which checks release lineage completion before allowing cleanup.

### 7.3 Ephemeral Environment Contract (AC-8)

**Creation:**
- Conduct creates ephemeral environments automatically when the project has the
  `ephemeral-env` capability (checked during dispatch).
- E1: `env-db.sh create {project} "YOK-{id}" --item "YOK-{id}"` with
  `status=pending`. Transitions to `starting` after the workflow run is found.
- The project's CI/deploy substrate handles actual provisioning (GitHub Actions
  workflow, Docker, etc.).

**Discovery:**
- Ephemeral URLs are resolved by `(project, branch)` query on
  `ephemeral_environments`.
- Branch naming contract: `YOK-{item-id}` matches the worktree branch name.
- For browser scenarios during validation, the Tester receives the ephemeral URL
  via conduct's E4 context injection.

**Cleanup:**
- E5: After Tester returns, conduct marks the environment `stopped` via
  `env-db.sh update {env_id} status stopped`.
- `env-db.sh cleanup` marks stale ephemeral environments (exceeding
  `max-age-hours`) as `stopped`.
- The project's CI substrate is responsible for actual resource teardown
  (container stop, instance termination).

### 7.4 Tables Are Not Unified

`deployment_preview_environments` and `ephemeral_environments` serve different
purposes and track different lifecycles. They must NOT be collapsed into a
single table:

- Preview: pooled resources managed at deployment-run level, with shared/adhoc
  semantics and lineage-based cleanup guards.
- Ephemeral: per-branch resources managed at validation level, with simple
  start/stop lifecycle and TTL-based cleanup.

---

## 8. Tester Derivation Workflow (AC-13, AC-15, AC-18)

### 8.1 From ACs to Scenarios

When the Tester agent receives an item for validation:

1. **Read ACs:** Parse the item's acceptance criteria from the body.
2. **Classify each AC:** Determine if the AC is browser-testable (see Section 9).
3. **Generate scenario requirements:** For each browser-testable AC, create a
   `qa_requirements` row with:
   - `qa_kind`: `e2e` (functional flow), `smoke` (quick health check), or
     `visual-regression` (visual comparison)
   - `qa_phase`: `verification`
   - `target_env`: Resolved by environment selection rules (Section 3)
   - `requirement_source`: `ac_derived`
   - `success_policy`: Scenario JSON (Section 1)
   - `capability_requirements`: `["browser"]`
4. **Execute scenarios:** Run each scenario against the target environment.
5. **Record results:** Create `qa_runs` entries with verdict, raw_result
   (step-by-step evidence plus the branch/SHA code identity for browser_substrate runs), and confidence scores (for agent-judged).
6. **Store artifacts:** Capture screenshots, traces, etc. in `qa_artifacts`.

### 8.2 Validation vs Deployment-Run Checks (AC-15)

| Aspect | Validation-phase (Tester) | Deployment-run (Usher) |
|---|---|---|
| **Scope** | Item's ACs and changed routes | Release-level smoke and critical paths |
| **requirement_source** | `ac_derived` | `flow_derived` or `explicit` |
| **qa_phase** | `verification` | `post_deploy` |
| **Authored by** | Tester agent during conduct | Flow defaults + durable suite + operator |
| **Target** | Ephemeral or preview env | Preview or production |
| **Lifecycle** | Ephemeral — tied to item validation | Persistent — part of release QA |

These are separate requirement populations. Validation checks are targeted and
narrow. Deployment-run checks are broad and draw from existing known-good
suites.

### 8.3 Promotion Path (AC-18)

AC-derived scenarios can graduate to durable suite tests when stable and broadly
useful:

1. **Stability signal:** A scenario has passed consistently across N consecutive
   runs (configurable, default: 5) without modification.
2. **Breadth signal:** The scenario covers a route or flow that is exercised by
   multiple items (not a one-off validation).
3. **Promotion action:** Operator or Tester marks the requirement with a
   `suite_id` value in the `qa_requirements` table. The suite_id links the
   requirement to a named test suite for ongoing tracking.
4. **Codification:** The scenario definition is extracted from `success_policy`
   and committed to the project repo as a test file (Playwright spec, shell
   test, etc.). The `qa_requirements` row remains as the tracking record.

Promotion is operator-initiated. Automated stability scoring may inform the
recommendation, but the final decision is human.

---

## 9. Classification Rules for Browser-Testable Work (AC-12)

### 9.1 Signals

An item is classified as browser-testable when ANY of these signals are present:

| Signal | Source | Weight |
|---|---|---|
| Project has browser QA capability | `project_capabilities` where `type='browser'` | Strong |
| Item ACs mention UI elements | AC text contains: `page`, `button`, `form`, `modal`, `render`, `display`, `visible`, `click`, `navigate`, `redirect`, `layout`, `style` | Moderate |
| Changed files include frontend code | Git diff includes `*.tsx`, `*.jsx`, `*.vue`, `*.svelte`, `*.css`, `*.scss`, `*.html`, `templates/**` | Moderate |
| Item type is `visual-regression` or `e2e` | Explicit item tagging | Strong |
| Item body references routes or URLs | Body text contains route patterns (`/path`, `GET /api`) | Weak |

### 9.2 Classification Logic

Classification is deterministic, not heuristic:

1. If the project does NOT have a `browser` capability declared in
   `project_capabilities`, the item is NOT browser-testable (no executor
   available).
2. If the project has `browser` capability AND any strong or two moderate
   signals are present, the item IS browser-testable.
3. Operator can override by explicitly setting or removing browser QA
   requirements on the item.

### 9.3 Default Requirements for Browser-Testable Items

When an item is classified as browser-testable:

- **Minimum:** At least one `qa_requirements` row with
  `capability_requirements` including `"browser"` must exist before the item
  enters `implementing` status.
- **For user-visible outcomes (AC-17):** Items that change user-visible browser
  behavior must include at least one `blocking` requirement with
  `check_style` of `deterministic`, `diff_aware`, or `agent_judged`. This
  ensures visual acceptance is not skipped for user-facing changes.

YOK-846 operationalizes the auto-attachment logic that enforces these defaults.

---

## 10. Durable vs Ephemeral vs Promoted Checks (AC-16)

### 10.1 Check Lifecycle Categories

| Category | requirement_source | suite_id | Lifespan | Description |
|---|---|---|---|---|
| **Durable suite** | `explicit` | set | Permanent | Repo-owned tests (Playwright specs, shell tests) that run on every deployment |
| **AC-derived ephemeral** | `ac_derived` | null | Item-scoped | Tester-generated scenarios tied to a specific item's ACs. Expire when the item is done. |
| **Promoted** | `ac_derived` | set | Permanent | Previously ephemeral scenarios that have been promoted to a named suite |
| **Flow-derived** | `flow_derived` | null or set | Run-scoped | Deployment flow defaults, materialized per run |

### 10.2 Distinguishing at Query Time

```sql
-- Durable suite tests
SELECT * FROM qa_requirements
WHERE requirement_source = 'explicit' AND suite_id IS NOT NULL;

-- Ephemeral item-scoped checks
SELECT * FROM qa_requirements
WHERE requirement_source = 'ac_derived' AND suite_id IS NULL;

-- Promoted checks (graduated from ephemeral)
SELECT * FROM qa_requirements
WHERE requirement_source = 'ac_derived' AND suite_id IS NOT NULL;

-- Deployment-run checks
SELECT * FROM qa_requirements
WHERE deployment_run_id IS NOT NULL;
```

---

## 11. Deployment-Run Browser QA (AC-14)

### 11.1 Scoping

Deployment-run browser QA is separate from item validation. It validates the
release, not the item:

- **Source:** Flow defaults (`deployment_flows.stages` with browser executor
  types), durable suite tests, promoted critical-path checks, and
  operator-added release checks.
- **Phase:** `post_deploy`
- **Target:** Preview environment (pre-production validation) or production
  (post-deploy smoke).
- **Creation:** Deployment pipeline materializes `qa_requirements` rows with
  `deployment_run_id` set and `requirement_source = 'flow_derived'`.

### 11.2 Stage-Specific Defaults (AC-14)

| Deployment stage executor | Browser QA behavior |
|---|---|
| `adaptive-e2e` | Runs browser scenarios from durable suite against target env |
| `health-check` | HTTP-level checks only (no browser scenarios) |
| `ephemeral-verify` | Verifies the preview deploy completed and surfaces the preview URL; it does not synthesize or satisfy item-level screenshot QA by itself |
| `test-suite` | Runs project test suite (may include browser tests) |

### 11.3 No Suite Synthesis at Deploy Time

Deployment-time browser QA draws from existing, pre-materialized checks. It
does NOT synthesize an entire new browser suite from scratch during deployment.
This is intentional: deployment checks should be known-good, pre-validated
scenarios, not novel AI-generated tests.

---

## 12. External Project Onboarding Contract (AC-19)

### 12.1 Required Capabilities

For a project to support browser QA scenarios, it must declare the following in
`project_capabilities`:

| Capability type | Required config fields | Description |
|---|---|---|
| `browser` | `playwright_config_path`, `browser_list` | Where Playwright config lives, which browsers to test |
| `ephemeral-env` | `workflow`, `github_ref_pattern`, `health_check_path`, `ttl_hours` | How Yoke triggers ephemeral environments |
| `github` | `owner`, `repo` | GitHub repo for Actions integration |
| `ssh` | `host`, `user`, `key_path` | Remote host for VPS-based deployments |

### 12.2 Optional Capabilities

| Capability type | Config fields | Description |
|---|---|---|
| `production-url` | `url` | Production URL for post-deploy smoke checks |
| `preview-pattern` | `name_template`, `url_template`, `creation_method` | How Yoke provisions named preview environments |
| `baseline-storage` | `path` | Where visual regression baselines are stored in the project repo |

### 12.3 Onboarding Checklist

For a new project to receive browser QA:

1. Add `browser` capability with Playwright config path.
2. Add `ephemeral-env` capability if branch-scoped environments are supported.
3. Add `github` capability for CI integration.
4. Optionally add `preview-pattern` for named preview environments.
5. Optionally add `baseline-storage` for visual regression baselines.
6. Run `/yoke doctor {project}` to verify capability configuration.

---

## 13. AC Coverage Matrix

| AC | Section | Status |
|---|---|---|
| AC-1: Scenario JSON schema | Section 1 | Covered |
| AC-2: Success policies per requirement | Section 2 | Covered |
| AC-3: Browser artifacts normalize | Section 6 | Covered |
| AC-4: Environment/base-URL injection | Section 3.3 | Covered |
| AC-5: Environment selection rules | Section 3.1 | Covered |
| AC-6: Preview vs ephemeral contracts | Section 7 | Covered |
| AC-7: Operator-requested preview environments | Section 7.2 | Covered |
| AC-8: Automatic ephemeral environments | Section 7.3 | Covered |
| AC-9: Preview conflict detection | Section 7.2 | Covered |
| AC-10: Preview cleanup semantics | Section 7.2 | Covered |
| AC-11: Three check styles | Section 4 | Covered |
| AC-12: Browser-testable classification | Section 9 | Covered |
| AC-13: Validation-phase targeting | Section 8.1 | Covered |
| AC-14: Deployment-run browser QA | Section 11 | Covered |
| AC-15: Validation vs deployment-run distinction | Section 8.2 | Covered |
| AC-16: Durable vs ephemeral vs promoted | Section 10 | Covered |
| AC-17: Visual acceptance blocking | Section 9.3 | Covered |
| AC-18: AC-derived promotion path | Section 8.3 | Covered |
| AC-19: Project onboarding contract | Section 12 | Covered |
| AC-20: Baseline selection rules | Section 5 | Covered |
| AC-21: Executor-agnostic schema | Section 1.5 | Covered |
