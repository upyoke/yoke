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

1. The project's verified one-shot migration package root. New migration ideas reference the live package that discovery resolves, never a guessed directory.
2. The live skill structure under `.agents/skills/yoke/` for skill-prose ideas.
3. The most recent completed work item of the same family (`yoke items list --status done` plus body inspection) for any other concrete-path category.

No path is written into the spec from naming intuition. If verification still fails after re-derivation, flag the unresolved reference as a clarification question in the spec rather than guessing.

### Prevention 2 — grep for gate/owner symbols before naming a control-plane file

When the spec proposes a control-plane implementation surface — a lifecycle gate, status-write gate, QA gate composition, or error-code owner — the agent first runs the canonical grep template against the live tree and cites the verified owner from the output. Naming intuition is not enough: gate composition is consolidated in helpers like `_run_authoritative_status_gate` (in `yoke_core.domain.backlog_updates_helpers`) and `check_verification_gate` (in `yoke_core.domain.qa_gates`), not in vocabulary-only files like `yoke_core.domain.task_lifecycle`.

Run this exact template (`<source-roots>` = this project's own source and test roots — see **Discovery-grep scoping** below for how to derive them):

```bash
rg -n 'def _run_.*_gate|def check_.*_gate|GATE_[A-Z_]+' <source-roots>
```

Pick the verified owner from the grep output and cite the resolved path/function in the spec — do not infer from a generic filename. Item stage, progression, and gate placement belong to immutable workflow definitions interpreted by `workflow_runtime.py`; independent epic-task vocabulary lives in `task_lifecycle.py`. If the grep returns zero matches for the family the spec is targeting, treat the absence as a clarification question rather than a guess.

This rule applies to gates, error codes (`GATE_*` constants), and any composition surface the spec proposes to extend or modify. Item-lifecycle changes target the workflow registry/definition owner; epic-task vocabulary changes target `task_lifecycle.py`. Proposed gate composition belongs in the live helper that grep names.

#### Prevention 2b — grep for ANY function the spec proposes to modify

The gate-specific template above is the narrow case. The general rule is broader: when the spec body proposes modifying, extending, editing, or adding behavior to any concrete `module.function_name` — not only gates — the agent runs:

```bash
rg -n '^def <funcname>' <source-roots> <docs-and-agent-instruction-roots>
```

and cites the verified `file:line` of the **definition** (not a caller). If the grep finds zero `def function_name` in the named module file, the spec records the unresolved reference as a clarification question rather than guessing.

This is the broader version of the gate template that catches the "spec named `yoke_core.domain.foo.bar` but the function actually lives in `module_other.py`" defect class. The pre-handoff readiness check at idea exit and refine entry runs this verification automatically through `yoke readiness check`.

**Discovery-grep scoping.** Scope discovery greps to *this* project's own roots — its source and test roots (`<source-roots>`), plus its docs and agent-instruction roots (`<docs-and-agent-instruction-roots>`) where relevant. Read those roots from the project rules file, or derive the tracked top-level ones with `git ls-files | cut -d/ -f1 | sort -u`; never assume another project's directory layout. No project stores item bodies on the filesystem (they are virtual: read them via `yoke items get PREFIX-N body` or the DB, never by grepping the filesystem). Use **single-quoted** `rg` patterns; an unescaped backtick inside a double-quoted zsh pattern triggers command substitution before `rg` runs.

## 1b. Active Path Claim Conflicts Are Coordination, Not Scope

**Rule:** claimed paths do not narrow work item scope. When inference (or later body drafting) discovers that a required file is already covered by another item's active or non-terminal path claim, do **not** remove the file from the work item, do **not** rewrite the spec to avoid the overlap, and do **not** narrow any enabled File Budget to whatever paths happen to be unclaimed. Active path claims are coordination/dependency/blocking facts about who currently coordinates work on a path — they never authorize omitting a required file from a new work item. "Avoid the overlap" never means "omit the required file."

The accepted remediations when an overlap is observed are:

- Classify the overlap via `yoke claims path coordination-decision-build` and author either a `coordination_only` compatibility edge (independent same-file edits, no lifecycle gate) or an explicit `--gate-point activation` row (order-dependent edits, with directional rationale).
- Leave the candidate claim in `state="blocked"` so the upstream coordination is surfaced explicitly.
- Wait for the holder to release the claim.
- Coordinate with the holder out of band.
- Ask the holder to narrow or cancel their claim.
- Use operator override (`path-claim-override`) only as a last resort.

Keep every required file in the execution artifact and in each enabled File
Budget or path-claim surface regardless of overlap. The path-claim workflow
handles the conflict downstream; idea intake does not. See `AGENTS.md`
`## Path Claims — Hard Rule` for the full rule.

## 2. Research And Infer All Fields From Context

Read the title, any body/description the user provided, and recent conversation context. Use this to infer all item metadata without asking:

### a. Infer project

First, query available projects:
```bash
_project_list=$(yoke db read --format lines "SELECT id FROM projects ORDER BY id" 2>/dev/null || true)
```

- If `_project_list` is empty or contains exactly one project, auto-select it (or `default_project` from config if empty):
 ```bash
 _project=$(python3 -m yoke_core.domain.runtime_settings get default_project yoke)
 _project=${_project:-yoke}
 ```
 Print: `Project: {_project} (auto-selected)`

- If `_project_list` contains multiple projects, infer from title/body keywords:
 - Keywords mentioning a specific project's domain, repo name, or technologies -> that project
 - Keywords like "Pack", "yoke script", "SKILL.md", "backlog" -> `yoke`
 - If truly ambiguous, ask ONE binary question: "Is this for {project-A} or {project-B}?"

After project is decided, resolve and print this machine's local checkout for that project when one exists; when `_project != yoke` that checkout is the only valid root for File Budget enumeration and path-claim authoring. Absence of a local checkout is a setup problem, not permission to inspect the Yoke repo for target-project files. See [file-budget.md](file-budget.md) for the project-relative path rule.

### b. Infer deployment flow

**This deploy-default lookup MUST run before deciding `_deployment_flow`.** For every project with a configured default, the lookup is non-skippable — running the fallback inference below without first running the lookup is wrong, not optional. The helper prints the flow id when a default is set and prints nothing when no default exists:
```bash
_project_default_flow=$(yoke project-structure deploy-defaults get --project "${_project}" || true)
```

If `_project_default_flow` is non-empty, use it as the deployment flow without further inference:
- Set `_deployment_flow` to `_project_default_flow`
- Print: `Deployment flow: {_deployment_flow} (project default)`

The fallback inference below applies only when the lookup returns nothing:
```bash
_flow_list=$(yoke workflows definition get --project "${_project}" 2>/dev/null || true)
```

- If `_flow_list` is empty -> no deployment flow applies; leave `_deployment_flow` empty
- If `_flow_list` contains exactly one non-internal flow -> auto-select it
- If `_flow_list` contains multiple flows -> infer from context (deployment-related work -> the deploy flow; docs/process work -> no flow, leaving `_deployment_flow` empty). Only ask if genuinely ambiguous.

If a flow applies, set `_deployment_flow` to its registered id (e.g., `yoke-internal`, `example-project-internal`). If no flow applies, leave `_deployment_flow` empty. NEVER store the literal string `none` — it is not a registered flow id and the CLI will reject it.

### c. Infer workflow

Read the active registry definitions before validating or inferring:

```bash
_workflow_registry_json=$(yoke workflows definition get \
 --project "${_project}" --json) || {
 echo "Cannot read the workflow registry."
 exit 1
}
```

The relevant rows are `result.workflows[]`. A candidate must be active and its
current definition must include `harness_skill` in `entry_surfaces`.

If the operator supplied `--workflow`:

- Match that exact registry id. Do not replace it with an inferred workflow.
- Reject an unknown, disabled, or entry-surface-incompatible row.
- Read its ordered `stages`, `skill_bindings`, and `policies`; do not branch
  on the workflow id.
- If its initial stage is owned directly by the `dash` skill, route to
  `/yoke dash "instruction"` so filing and the direct-execution contract are
  created atomically.
- If its bindings hand from `refine` to `blitz`, preserve that registered
  boundary: refinement links exactly one execution strategy document, then
  Blitz executes it. Intake does not copy the plan into the item body or
  bypass refinement.

Without `--workflow`, classify the eligible definitions by policy:

- Prefer the unique smallest implementation workflow with
  `generated_children=none`, `worktrees=single_implementation_lane`, and an
  `advance` skill binding.
- Recommend the unique task-graph workflow with
  `generated_children=epic_tasks` and `parallelism=task_graph` only when the
  work clearly needs:
- Multiple parallel worktrees
- A spec plus task decomposition
- More than ~2 hours of focused work

If the work is borderline, ask one binary question using the two matched
workflow display names: "This looks like it might need task decomposition.
Use {task-graph workflow} or {single-lane workflow}?"

If either policy shape has zero or multiple eligible matches, ask the operator
to select from those registry rows instead of guessing. Workflow ids such as
`issue` and `epic` are built-in registry keys, not item types or lifecycle
branches.

**Pre-decomposition guard:** Never file separate backlog items as a parent's
imagined child decomposition. Backlog items are flat rows in `items`. When the
selected definition declares `generated_children=epic_tasks`, the Architect
populates those rows inside the registered planning skill; do not gate this
rule on a remembered item status.

### d. Infer priority from language

Scan title and body for signal words. Never ask about priority.
- **High:** "urgent", "broken", "prod", "blocking", "hotfix", "critical", "P0", "emergency", "outage", "down"
- **Low:** "nice-to-have", "future", "someday", "eventually", "minor", "cosmetic", "cleanup"
- **Medium:** everything else

### e. Auto-detect dependencies

Scan title and body for explicit `PREFIX-N` references. If found:
- Validate each referenced item exists:
 ```bash
 yoke items get PREFIX-{N} status
 ```
- Auto-record as activation blocker
- Print: `Auto-detected dependency: PREFIX-{N} (gate: activation, satisfaction: status:done)`

If no `PREFIX-N` references are found, skip silently.

### f. Infer Pack-reuse stance

If `_project` is NOT `yoke`, every project-side work item must declare whether the change belongs only to that project or also to a reusable Pack. Infer from title/body:

- **`project-owned`** — The result is specific to this project; customized Pack files remain project-owned and need no central exception record.
- **`pack-update`** — The general capability should ship as a new Pack version and then be previewed/applied in the target project. Cross-repo delivery follows the companion-item rule in `AGENTS.md` (`## Project Scoping`): the Pack version ships from the Pack-owning project's item, and applying it lands in a linked companion item in this project.

Decision test: "Would another project reasonably want this reusable capability change when it updates the same Pack?"
- Yes -> `pack-update`
- No -> `project-owned`

If the stance cannot be inferred from context, ask ONE binary question:
> Pack reuse: Is this change project-owned, or should it become a reusable Pack update? (project-owned / pack-update)

Set `_pack_stance` to the inferred value. If `_project` is `yoke`, set `_pack_stance=""`.

Print the inference summary:
```text
Inferred fields:
 Project: {_project}
 Workflow: {workflow}
 Priority: {priority}
 Deployment flow: {_deployment_flow or "(no flow — flag will be omitted)"}
 Dependencies: {list or "none"}
 Pack reuse: {_pack_stance or "n/a (yoke project)"}
```

## 3. Cross-Project Detection (Hard Block)

Before proceeding, check if the title/body implies work touching files in more than one project repo. If detected, STOP -- do not create a single work item spanning multiple projects. Each project's share becomes its own work item in that project, and the items are linked as companion items by an `item_dependencies` edge (`AGENTS.md`, `## Project Scoping`). One session may later claim both items and execute both lanes; a single item never gets a lane in a second repo.

### Independent work per project

- Signals: distinct, separately deliverable work items per project
- Action: Propose splitting into companion items -- one per project -- with a hard-block dependency between them
- Gate message:
 ```text
 GATE [hard-block]: Cross-project work detected.
 This idea touches both {project-A} and {project-B}.
 Remediation: File one work item per project, linked as companion items.
 Create both work items with a hard-block dependency? (Yes / No)
 ```
- If yes, create both work items by repeating this phase and the body phase for each
- If no, let the user clarify scope

### Coordinated work led by one project

- Signals: publish-a-Pack-update then install/deploy/verify it, or similar work where one project's change must land before the other project can consume it
- Action: File the leading item in the project that owns the change plus a companion item in the consuming project, linked so the consuming item is the dependent side
- Proceed without asking
- Name the companion item in each body and say what the dependent side waits on

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
yoke items get PREFIX-{N} body
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
commit names the same subsystem, feature, or work item family, inspect the
referenced item body or commit diff before deciding this is new work.

Run the dedup search:

```bash
yoke items search "{keywords}" --project "${_project}"
```

Use 2-3 keywords extracted from the proposed title. Because this search is
literal phrase matching, run it after the board-context scan rather than
treating it as the only duplicate check. Classify each result as title match,
body match, or scope overlap.

If matches found, present:
```text
GATE [advisory]: Near-duplicate detected.
Potential duplicates found:
- PREFIX-{N}: {title} (status: {status}) [match workflow]

Remediation: Review the existing item(s) above. If this is truly new work, confirm below.
Create anyway? (yes / no)
```

- If **no** -> stop and suggest updating the existing item instead
- If **yes** -> proceed
- If **no matches** -> proceed silently

## 5. Create The Item Through Its Registered Entry Surface

`yoke items create` is the registered work-item create surface. It works in a Yoke checkout and over a prod-https control plane through the same `FunctionCallRequest`. This skill always passes `--entry-surface harness_skill`; the selected workflow version must allow that surface. **Run the command BARE — do NOT append `2>&1`, `| head`, `| tail`, or any other shell wrapping** (it is a registered `yoke` adapter; the harness surfaces stdout and stderr in your prompt context on the next turn, and the shell-quoted-function-payload lint refuses write-shape adapters with non-best-effort wrapping). Read the rendered output inline and act on it from the prompt context.

Title and workflow are positional; project / deployment-flow / priority are flags. Build the command with `--project` and optionally `--deployment-flow`:

```bash
yoke items create "{title}" {workflow} --entry-surface harness_skill --project "${_project}" --deployment-flow "${_deployment_flow}" --priority {priority}
```

The adapter dispatches function id `items.create` to a global target with this
payload shape:

```text
{
  "title": "{title}",
  "workflow": "{workflow}",
  "entry_surface": "harness_skill",
  "project": "{_project}",
  "priority": "{priority}",
  "deployment_flow": "{_deployment_flow}"  # omitted when empty
}
```

For `/yoke idea --workflow blitz`, `{workflow}` is literally `blitz`; it is
not an instruction field, posture choice, or later migration.

If `_deployment_flow` is empty, omit that flag:

```bash
yoke items create "{title}" {workflow} --entry-surface harness_skill --project "${_project}" --priority {priority}
```

If `--dry-run` was passed, add `--dry-run` (no row is created, no GitHub sync; status defaults to `idea`):

```bash
yoke items create "{title}" {workflow} --entry-surface harness_skill --dry-run --project "${_project}" --priority {priority}
```

## 5b. Hold A Draft Claim Across The Body-Write Window (Layer 1)

The window between phase 5 (`items add` returns a PREFIX-N row with empty
spec) and the body-write in `body-and-sync.md` is unprotected against
concurrent `/yoke do` sessions. Hold a draft work claim across that
window so a second harness's `yoke sessions offer` cannot route `/yoke refine`
against an empty spec.

```bash
yoke claims work acquire \
    --item "PREFIX-{id-number}" \
    --reason draft-in-progress
```

The claim is the live-race fix; `body-and-sync.md` releases it with
`--reason idea-complete` once the spec body, AC normalization, and File
Budget have all landed. Skip in `--dry-run` mode (no row to claim).

The configured stale-heartbeat reclaim window (`session_stale_ttl_minutes`
in machine config) in the harness session store is the safety net
for a crashed `/yoke idea` — during that window the half-finished work item
is intentionally unworkable, and `yoke_core.domain.frontier_compute`
flags the title-only body explicitly via `idea-incomplete` so doctor and
operators can rescue or freeze it.

## 6. Persist Dependencies

If dependencies were auto-detected, persist them now that the item has a PREFIX-N ID. This uses the registered dependency-edge wrapper.

```bash
yoke shepherd dependency-add {new-item-id} {blocking-item-id} operator --gate-point activation \
 --satisfaction status:done --rationale "Auto-detected from PREFIX-{blocking} reference in idea title/body"
```

Dry-run mode: print what would be persisted instead of mutating state.

## 7. Display Creation Confirmation

Read the created item from the DB and display a confirmation. If GitHub issue creation succeeded, include the linked issue number. If dependencies were detected, include them in the confirmation output.

Read the created item's immutable pin with `yoke workflows item get`, read that
exact version with `yoke workflows version get`, and resolve the active
half-open skill binding. Print the definition-owned handoff:

```text
Next step: /yoke {skill_id} PREFIX-{N}
```

If the definition's later binding is `blitz`, also print the refinement and
execution handoff:

```text
Next step: /yoke refine PREFIX-{N}
After refinement links exactly one execution strategy document and the item
reaches refined-idea: /yoke blitz PREFIX-{N}
```

The link is the registered `strategy.execution.link` operation. Do not start
`/yoke blitz`, generate child items, or treat the intake body as the live
execution plan before that link exists. For every other workflow, recompute the
next skill at each binding boundary instead of printing a workflow-name
progression from memory.
