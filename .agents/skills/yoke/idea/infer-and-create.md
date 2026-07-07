# Idea Phase: Infer Fields And Create The Item
This phase owns the metadata inference, cross-project guardrails, duplicate check, item creation, dependency persistence, and creation confirmation for `/yoke idea`.

## 1a. Pre-Body Reference Verification (Prevention 1 + 2)

When `/yoke idea` proposes concrete file paths, package roots, or owner-symbol names that will land in the spec body, every reference must be **verified against the live tree before it is written**. Naming intuition is not enough — historical familiarity drifts as the codebase evolves, and a wrong file reference makes refine and execution chase ghosts.

Apply both rules below any time the agent composes body content for the spec — during inference (section 2), during body drafting in `body-and-sync.md`, or any later edit that introduces an implementation surface.

### Prevention 1 — verify concrete file/package paths before writing them

When the spec proposes a concrete implementation path (a file, directory, or package root the implementation will edit or create), run an explicit verification verb **before** the path is written into the body:

- **Directory or package root** — `test -d <path>` from the repo root. If the directory does not exist, do not write the path.
- **Specific file or file pattern** — use the Glob tool with the proposed pattern. If Glob returns no matches, do not write the path.

If the path does not resolve, re-derive from the live tree before writing. Canonical re-derivation sources, in order:

1. `runtime/api/domain/migrations/__init__.py` for the live one-shot migration package root. New migration ideas reference this directory, never `runtime/api/migrations/` (which does not exist).
2. The live skill structure under `.agents/skills/yoke/` for skill-prose ideas.
3. The most recent completed ticket of the same family (`yoke items list --status done` plus body inspection) for any other concrete-path category.

No path is written into the spec from naming intuition. If verification still fails after re-derivation, flag the unresolved reference as a clarification question in the spec rather than guessing.

### Prevention 2 — grep for gate/owner symbols before naming a control-plane file

When the spec proposes a control-plane implementation surface — a lifecycle gate, status-write gate, QA gate composition, or error-code owner — the agent first runs the canonical grep template against the live tree and cites the verified owner from the output. Naming intuition is not enough: gate composition is consolidated in helpers like `_run_authoritative_status_gate` (in `runtime/api/domain/backlog_updates_helpers.py`) and `check_verification_gate` (in `runtime/api/domain/qa_gates.py`), not in vocabulary-only files like `runtime/api/domain/lifecycle.py`.

Run this exact template:

```bash
rg -n "def _run_.*_gate|def check_.*_gate|GATE_[A-Z_]+" runtime/api/domain runtime/api
```

Pick the verified owner from the grep output and cite the resolved path/function in the spec — do not infer from a generic filename like `lifecycle.py` (which owns status vocabulary and progression, not gate composition). If the grep returns zero matches for the family the spec is targeting, treat the absence as a clarification question rather than a guess.

This rule applies to gates, error codes (`GATE_*` constants), and any composition surface the spec proposes to extend or modify. Pure status/progression edits to `lifecycle.py` are still legitimate when the spec is changing the lifecycle vocabulary itself, but proposed gate composition belongs in the helper that grep names.

#### Prevention 2b — grep for ANY function the spec proposes to modify

The gate-specific template above is the narrow case. The general rule is broader: when the spec body proposes modifying, extending, editing, or adding behavior to any concrete `module.function_name` — not only gates — the agent runs:

```bash
rg -n "^def <funcname>" runtime/ docs/ .agents/
```

and cites the verified `file:line` of the **definition** (not a caller). If the grep finds zero `def function_name` in the named module file, the spec records the unresolved reference as a clarification question rather than guessing.

This is the broader version of the gate template that catches the "spec named `yoke_core.domain.foo.bar` but the function actually lives in `module_other.py`" defect class. The pre-handoff readiness check at idea exit and refine entry runs this verification automatically through `yoke readiness check`.

**Discovery-grep scoping.** Scope discovery greps to `runtime/api/` (plus `docs/` and `.agents/` where relevant) — Yoke has **no top-level `tests/` directory** (the Yoke API tests live under `runtime/api/`) and **no `data/items/` directory** (item bodies are virtual: read them via `yoke items get YOK-N body` or the DB, never by grepping the filesystem). Use **single-quoted** `rg` patterns; an unescaped backtick inside a double-quoted zsh pattern triggers command substitution before `rg` runs.

## 1b. Active Path Claim Conflicts Are Coordination, Not Scope

**Rule:** claimed paths do not narrow ticket scope. When inference (or later body drafting) discovers that a required file is already covered by another item's active or non-terminal path claim, do **not** remove the file from the ticket, do **not** rewrite the spec to avoid the overlap, and do **not** narrow the File Budget to whatever paths happen to be unclaimed. Active path claims are coordination/dependency/blocking facts about who currently coordinates work on a path — they never authorize omitting a required file from a new ticket. "Avoid the overlap" never means "omit the required file."

The accepted remediations when an overlap is observed are:

- Classify the overlap via `yoke claims path coordination-decision-build` and author either a `coordination_only` compatibility edge (independent same-file edits, no lifecycle gate) or an explicit `--gate-point activation` row (order-dependent edits, with directional rationale).
- Leave the candidate claim in `state="blocked"` so the upstream coordination is surfaced explicitly.
- Wait for the holder to release the claim.
- Coordinate with the holder out of band.
- Ask the holder to narrow or cancel their claim.
- Use operator override (`path-claim-override`) only as a last resort.

Keep every required file in the File Budget and in this item's path-claim attempt regardless of overlap. The path-claim workflow handles the conflict downstream; idea intake does not. See `AGENTS.md` `## Path Claims — Hard Rule` for the full rule.

## 2. Research And Infer All Fields From Context

Read the title, any body/description the user provided, and recent conversation context. Use this to infer all item metadata without asking:

### a. Infer project

First, query available projects:
```bash
_project_list=$(python3 -m yoke_core.cli.db_router query "SELECT id FROM projects ORDER BY id" 2>/dev/null || true)
```

- If `_project_list` is empty or contains exactly one project, auto-select it (or `default_project` from config if empty):
 ```bash
 _project=$(python3 -m yoke_core.domain.runtime_settings get default_project yoke)
 _project=${_project:-yoke}
 ```
 Print: `Project: {_project} (auto-selected)`

- If `_project_list` contains multiple projects, infer from title/body keywords:
 - Keywords mentioning a specific project's domain, repo name, or technologies -> that project
 - Keywords like "template", "yoke script", "SKILL.md", "backlog" -> `yoke`
 - If truly ambiguous, ask ONE binary question: "Is this for {project-A} or {project-B}?"

After project is decided, resolve and print this machine's local checkout for that project when one exists; when `_project != yoke` that checkout is the only valid root for File Budget enumeration and path-claim authoring. Absence of a local checkout is a setup problem, not permission to inspect the Yoke repo for target-project files. See [file-budget.md](file-budget.md) for the project-relative path rule.

### b. Infer deployment flow

**This deploy-default lookup MUST run before deciding `_deployment_flow`.** For projects with a configured default (today: `yoke`, `buzz`), the lookup is non-skippable — running the fallback inference below without first running the lookup is wrong, not optional. The helper prints the flow id when a default is set and prints nothing when no default exists:
```bash
_project_default_flow=$(yoke project-structure deploy-defaults get --project "${_project}" || true)
```

If `_project_default_flow` is non-empty, use it as the deployment flow without further inference:
- Set `_deployment_flow` to `_project_default_flow`
- Print: `Deployment flow: {_deployment_flow} (project default)`

The fallback inference below applies only when the lookup returns nothing:
```bash
_flow_list=$(python3 -m yoke_core.cli.db_router flows list --project "${_project}" 2>/dev/null || true)
```

- If `_flow_list` is empty -> no deployment flow applies; leave `_deployment_flow` empty
- If `_flow_list` contains exactly one non-internal flow -> auto-select it
- If `_flow_list` contains multiple flows -> infer from context (deployment-related work -> the deploy flow; docs/process work -> no flow, leaving `_deployment_flow` empty). Only ask if genuinely ambiguous.

If a flow applies, set `_deployment_flow` to its registered id (e.g., `yoke-internal`, `buzz-internal`). If no flow applies, leave `_deployment_flow` empty. NEVER store the literal string `none` — it is not a registered flow id and the CLI will reject it.

### c. Infer type

Default: `issue`. Only recommend `epic` when the work clearly needs:
- Multiple parallel worktrees
- A spec plus task decomposition
- More than ~2 hours of focused work

If the work is borderline, ask ONE binary question: "This looks like it might need task decomposition. Epic or issue?"

Otherwise, auto-select `issue`. Never ask for clearly simple items.

**Pre-decomposition guard:** Never file additional issues attached to an epic that has not yet reached `planned` status. Backlog items are flat rows in `items`; epic decomposition lives in `epic_tasks`, populated by the Architect during shepherd planning.

### d. Infer priority from language

Scan title and body for signal words. Never ask about priority.
- **High:** "urgent", "broken", "prod", "blocking", "hotfix", "critical", "P0", "emergency", "outage", "down"
- **Low:** "nice-to-have", "future", "someday", "eventually", "minor", "cosmetic", "cleanup"
- **Medium:** everything else

### e. Auto-detect dependencies

Scan title and body for explicit `YOK-N` references. If found:
- Validate each referenced item exists:
 ```bash
 yoke items get YOK-{N} status
 ```
- Auto-record as activation blocker
- Print: `Auto-detected dependency: YOK-{N} (gate: activation, satisfaction: status:done)`

If no `YOK-N` references are found, skip silently.

### f. Infer template-propagation stance

If `_project` is NOT `yoke`, every project-side ticket must declare a template-propagation stance. Infer from title/body:

- **`project-only`** — Project-specific, outside template-managed areas
- **`project-and-template`** — The shared template should also get this fix
- **`template-deviation`** — A template-managed area intentionally diverges and must be recorded in `DEVIATIONS.md`

Decision test: "If we created another app from the Yoke webapp template, should it inherit this fix?"
- Yes -> `project-and-template`
- No, outside template-managed areas -> `project-only`
- No, inside template-managed areas but intentionally different -> `template-deviation`

If the stance cannot be inferred from context, ask ONE binary question:
> Template propagation: Is this change project-specific, or should the shared template also get it? (project-only / project-and-template / template-deviation)

Set `_template_stance` to the inferred value. If `_project` is `yoke`, set `_template_stance=""`.

### g. Infer browser QA metadata

Every new item gets a validated `browser_qa_metadata` object persisted at creation time. The object shape is fixed:

```json
{
 "browser_testable": false,
 "visual_outcome": false,
 "browser_routes": [],
 "browser_timing_hints_ms": []
}
```

Decide each field from title + body + any acceptance criteria the user already wrote. Condition on whether this ticket ships code that affects what an end user sees in a web browser — not on whether the body merely mentions URLs, settings, or dashboards in passing.

- **`browser_testable`** — `true` when the change renders, mutates, or exercises a user-facing page or UI surface. Login pages, dashboards, modals, form flows, theme swaps, animation additions, visible empty/error states. `false` for backend-only work, CLI tooling, infrastructure, config, docs, classifier/extraction logic, or anything where "browser QA" would capture nothing meaningful.
- **`visual_outcome`** — `true` when the change produces a visible UI result that screenshot evidence would improve (animations, theme/layout changes, new visible components, visible state transitions). `visual_outcome=true` requires `browser_testable=true`; the validator rejects the contradiction.
- **`browser_routes`** — explicit leading-slash relative routes the change targets (`/login`, `/forgot-password`, `/`). Lowercase. Route-form words in non-URL prose (`backend service settings`, `account management docs`, `dashboard rollout strategy`) are NOT routes — leave them out.
- **`browser_timing_hints_ms`** — integer milliseconds for any explicit pre-screenshot delay implied by AC language such as "visible 7 seconds after load" or "fade-in completes in 1500 ms". Empty when no AC makes timing explicit. Never include a floor or padding value here — the browser QA executor applies the 2000 ms settle-delay floor.

Non-browser tickets record the explicit negative object above — not `null`, not an empty string. The validator at `yoke_core.domain.browser_qa_metadata.validate` rejects contradictions, malformed shape, bad routes, and out-of-range timings; assemble the object so it passes validation before persistence.

Store the resulting object in `_browser_qa_metadata_json` as a compact JSON string. `body-and-sync.md` owns the persistence step.

Print the inference summary:
```text
Inferred fields:
 Project: {_project}
 Type: {type}
 Priority: {priority}
 Deployment flow: {_deployment_flow or "(no flow — flag will be omitted)"}
 Dependencies: {list or "none"}
 Template stance: {_template_stance or "n/a (yoke project)"}
 Browser QA: testable={browser_testable}, visual={visual_outcome}, routes={browser_routes or "[]"}, timings_ms={browser_timing_hints_ms or "[]"}
```

## 3. Cross-Project Detection (Hard Block)

Before proceeding, check if the title/body implies work touching files in more than one project repo. If detected, STOP -- do not create a single ticket spanning multiple projects.

### Pattern A: Split into two tickets

- Signals: distinct independent work items per project
- Action: Propose splitting into two tickets with a hard-block dependency between them
- Gate message:
 ```text
 GATE [hard-block]: Cross-project work detected.
 This idea touches both {project-A} and {project-B}.
 Remediation: Split into two tickets -- one per project.
 Create both tickets with a hard-block dependency? (Yes / No)
 ```
- If yes, create both tickets by repeating this phase and the body phase for each
- If no, let the user clarify scope

### Pattern B: Single multi-repo ticket under `yoke`

- Signals: template-then-render work or similar coordinated Yoke-led work
- Action: File under `project=yoke`, note multi-repo scope in the body
- Proceed without asking
- Add a note in the body: "Multi-repo scope: render/deploy/verify tasks will be defined during shepherd."

If the work is clearly single-project, skip this step.

## 4. Check For Duplicates Before Creating (Advisory)

First read the first 300 lines of the generated board view:

```bash
sed -n '1,300p' .yoke/BOARD.md
```

Use that board context to scan current active, refined, planned, and blocked
items in the same project for nearby titles or obvious scope overlap before
creating anything. If a likely match appears, inspect the existing item's
body before proceeding:

```bash
yoke items get YOK-{N} body
```

Classify any board-derived candidate as a title match, scope overlap, or
adjacent-but-distinct work item. Treat a board-derived likely match the same
way as a `dedup-search` result in the advisory gate below.

Also scan the recent commit titles before creating anything:

```bash
git log --oneline -10
```

Use recent commits to catch "already landed" or "just cancelled/replaced"
work that may not be prominent in the active board sections. If a recent
commit names the same subsystem, feature, or ticket family, inspect the
referenced item body or commit diff before deciding this is new work.

Run the dedup search:

```bash
python3 -m yoke_core.cli.db_router items dedup-search "{keywords}"
```

Use 2-3 keywords extracted from the proposed title. Because this search is
literal phrase matching, run it after the board-context scan rather than
treating it as the only duplicate check. Classify each result as title match,
body match, or scope overlap.

If matches found, present:
```text
GATE [advisory]: Near-duplicate detected.
Potential duplicates found:
- YOK-{N}: {title} (status: {status}) [match type]

Remediation: Review the existing item(s) above. If this is truly new work, confirm below.
Create anyway? (yes / no)
```

- If **no** -> stop and suggest updating the existing item instead
- If **yes** -> proceed
- If **no matches** -> proceed silently

## 5. Run The Backlog Registry Script To Create The Item

`yoke items create` is the sanctioned idea-intake create surface. It works in a Yoke checkout AND over a prod-https control plane — the same `FunctionCallRequest` either way — so `/yoke idea` files a ticket whether or not the machine has a Yoke source checkout. Pass `--idea-intake` on every production create: public create surfaces gate on sanctioned idea intake (`yoke_core.domain.ticket_intake_provenance.enforce_public_create_allowed`) and reject calls without it; `--idea-intake` is the flag form of the `provenance="idea"` signal (dry-run and test-isolated DB targets bypass the gate). **Run the command BARE — do NOT append `2>&1`, `| head`, `| tail`, or any other shell wrapping** (it is a registered `yoke` adapter; the harness surfaces stdout AND stderr in your prompt context on the next turn, and the shell-quoted-function-payload lint refuses write-shape adapters with non-best-effort wrapping). Read the rendered output inline and act on it from the prompt context (same shape as `/yoke do` Step A's "Parse the JSON from stdout in the prompt context" teaching).

Title and type are positional; project / deployment-flow / priority are flags. Build the command with `--project` and optionally `--deployment-flow`:

```bash
yoke items create "{title}" {type} --idea-intake --project "${_project}" --deployment-flow "${_deployment_flow}" --priority {priority}
```

If `_deployment_flow` is empty, omit that flag:

```bash
yoke items create "{title}" {type} --idea-intake --project "${_project}" --priority {priority}
```

If `--dry-run` was passed, add `--dry-run` (no row is created, no GitHub sync; status defaults to `idea`):

```bash
yoke items create "{title}" {type} --idea-intake --dry-run --project "${_project}" --priority {priority}
```

## 5b. Hold A Draft Claim Across The Body-Write Window (Layer 1)

The window between phase 5 (`items add` returns a YOK-N row with empty
spec) and the body-write in `body-and-sync.md` is unprotected against
concurrent `/yoke do` sessions. Hold a draft work claim across that
window so a second harness's `yoke sessions offer` cannot route `/yoke refine`
against an empty spec.

```bash
yoke claims work acquire \
    --item "YOK-{id-number}" \
    --reason draft-in-progress
```

The claim is the live-race fix; `body-and-sync.md` releases it with
`--reason idea-complete` once the spec body, AC normalization, and File
Budget have all landed. Skip in `--dry-run` mode (no row to claim).

The configured stale-heartbeat reclaim window (`session_stale_ttl_minutes`
in machine config) in `runtime.harness.harness_sessions` is the safety net
for a crashed `/yoke idea` — during that window the half-finished ticket
is intentionally unworkable, and `yoke_core.domain.frontier_compute`
flags the title-only body explicitly via `idea-incomplete` so doctor and
operators can rescue or freeze it.

## 6. Persist Dependencies

If dependencies were auto-detected, persist them now that the item has a YOK-N ID. This uses the registered dependency-edge wrapper.

```bash
yoke shepherd dependency-add {new-item-id} {blocking-item-id} operator --gate-point activation \
 --satisfaction status:done --rationale "Auto-detected from YOK-{blocking} reference in idea title/body"
```

Dry-run mode: print what would be persisted instead of mutating state.

## 7. Display Creation Confirmation

Read the created item from the DB and display a confirmation. If GitHub issue creation succeeded, include the linked issue number. If dependencies were detected, include them in the confirmation output.

Always end with:
```text
Next step: /yoke shepherd YOK-{N}
```
