# Subagent Reference (internal)

Canonical behavior lives in `runtime/agents/{role}.md`, with phase support in each
role directory. Read those owners before dispatch/review; this is contributor
discovery, not a second prompt registry. [Prompt philosophy](prompt-philosophy.md)
owns shared doctrine: complete durable artifacts, current-state checkpoints and
codebase-reader names that explain function without planning provenance.

## Bodies, adapters and dispatch

The substrate renderer expands one canonical body into each harness adapter:

| Harness | Rendered adapter | Native discovery |
|---|---|---|
| Claude | `runtime/harness/claude/agents/yoke-{role}.md` | `.claude/agents` symlink |
| Codex | `runtime/harness/codex/agents/yoke-{role}.toml` | `.codex/agents` symlink |

Claude YAML metadata comes from `runtime/agents/{role}.claude.json`. Codex TOML
uses `name`, `description`, `developer_instructions`; optional `model` is emitted
only for a sidecar's explicit pinned policy, otherwise inherited. Claude tool
allowlists/model nicknames/turn fields do not become Codex config. Harness
conditional expansion selects declared primitives while retaining the same
canonical responsibility. Details: [harness substrate](harness-substrate.md),
[manifest schema](../runtime/harness/manifest-schema.md) and actual manifests.
`canonical_agents` in bootstrap/manifest points to bodies without embedding them.

Shared `DispatchDescriptor` envelopes own role identity/context and harness call
shape. Lane reversal changes adapter and lane owner, preserving canonical persona;
skills use descriptors rather than Claude `subagent_type` branches. Codex Desktop
dispatches rendered custom agents through native primitives. `/yoke conduct` is
supported on Claude and Codex; capability truth is the installed release manifest.
`yoke agents render check` and `HC-agent-canonical-drift` check rendered parity.

Shepherd and Conduct run inline as skills, invoking roles; Usher owns delivery
inline too. They are not agents. The item's immutable workflow pin selects phase,
gates and bindings: [lifecycle](../.yoke/docs/reference/lifecycle.md). Project
verification anchors are its `.yoke/test-inventory.md`, never a copied repo layout.

## Role owners and tool boundaries

| Role | Canonical body | Responsibility |
|---|---|---|
| Product Manager | [product-manager](../runtime/agents/product-manager.md) | Complete missing PRD/spec sections from supplied context |
| Product Designer | [product-designer](../runtime/agents/product-designer.md) | UX patterns, flows, interactions, accessibility and reuse |
| Architect | [architect](../runtime/agents/architect.md) | Technical plan, task specs and lane plan |
| Engineer | [engineer](../runtime/agents/engineer.md) | Implementation, incremental commits and durable submission |
| Tester | [tester](../runtime/agents/tester.md) | Read-only completeness/contract/test/doc review and binary verdict |
| QA Walker | [qa-walker](../runtime/agents/qa-walker.md) | One exploratory mission, ranked findings or human gate |
| Simulator | [simulator](../runtime/agents/simulator.md) | Cross-task plan/integration gap tracing |
| Boss | [boss](../runtime/agents/boss.md) | Parameterized spec/PRD/plan quality gate |

Claude sidecars currently grant PM/Designer Read/Grep/Glob, no Bash/Write/Edit;
Architect/Tester/QA Walker/Simulator/Boss also Bash, no code Write/Edit; Engineer
code Write/Edit/Bash plus read tools. Engineer, Tester and QA Walker also grant
Monitor. All eight Claude sidecars currently declare opus and maxTurns300;
Engineer uses bypassPermissions for unattended dispatch. These are Claude facts,
not universal model/tool settings. Read sidecars, rendered hooks and active
manifest before changing grants. Cursor QA Walker has `readonly: false` to permit
mission substrate state changes while repository writes remain forbidden.

### Product Manager and Product Designer

PM is a single-pass prerequisite on the binding-derived plan-production edge
when required PRD sections are missing. It receives description/codebase/context
and clarifications, infers available answers, records real ambiguity in Open
Questions, and returns structured problem/users/goals/non-goals/requirements/
stories/technical considerations. It cannot ask the user itself.

Designer is optional for UI work; it may recommend skipping non-UI work. It
returns flows, screens/components, interactions, accessibility and existing
patterns. Parent persists `design_spec`; PM's parent persists typed spec fields.
Both enrich substantive operator content/structure/decisions instead of replacing
the rendered item or writing a filesystem draft as authority.

### Architect

Produces `technical_plan`, full `epic_tasks`/file manifests and `worktree_plan`
for parent persistence through registered surfaces. Read
[hard constraints](../runtime/agents/architect/hard-constraints.md) before planning:
session-fit XS/S/M/L (no XL), independent lanes/ordered tasks, FR-to-task coverage,
epic-size review, tests/docs, exact downstream contracts, DB→rendered views,
subprocess environment/cwd/error contracts, discovery and bounded reads.
Effective File Budget and path claims are independent; all required scope stays.
Task metadata names lane, context estimate and dependency task numbers.

Read [decomposition](../runtime/agents/architect/worktree-decomposition.md),
[lane template](../runtime/agents/architect/worktree-plan-template.md) and
[cross-script contracts](../runtime/agents/architect/cross-script-contracts.md)
at their actions. Verified shared-file overlap gets an attested independence or
directional dependency; ambiguity routes to Refine/operator, not runtime guesses.

Fix mode requires a gap report AND the phrase `fix mode`; spec-only input is
normal planning. [Fix-mode owner](../runtime/agents/architect/fix-mode.md) retains
CRITICAL/ WARNING/ NOTE dispositions, exact affected-task scope and full-artifact
output. Preserve unrelated content, numbering/order/lane assignments; no task
splitting/restructuring or code edits. File changes update lane manifest and
overlap check. Code fixes require `/yoke amend`; epic-wide changes require manual
epic update. Only explicitly missing FR Traceability permits regenerating that
section from corrected task mapping. Parent writes returned task bodies and
changed lane plan through structured commands, never task Markdown files as DB
authority. Every gap appears in the summary, including summary-only/manual routes.

### Engineer

Implement the exact task/interface scope in its registered lane. Commit each
completed unit, record progress through `yoke workflow-item epic-progress-note append`,
and return the durable six-key submission receipt newer than the
attempt's note watermark. Registered owners sync notes to GitHub; control-plane
writes use the main authority despite lane cwd. Missing/mismatched interfaces
report a blocker; discovered work goes to parent, not a new item from Engineer.

Root-cause protocol: read failing assertion, trace path, identify discrepancy,
record root cause, then fix. Capture large command output once; inspect retained
capture by targeted ranges/counts, never live-pipe to tail/head or rerun for lost
output. Role definition owns path grants, Pack-first behavior, naming, claim
widen-before-write and test selection. At ≤30 turns remaining, or uncertain
budget, enter submission mode: finish current deliverable/commit/notes, no new
implementation, optional cleanup or broad exploration.

### Tester

Tester never edits code, widens/overrides claims or waives required scope. Claude
tool allowlist, disallowedTools and PreToolUse enforcement protect read-only
review; authorized report/registered verdict writes do not grant source edits.
Review every AC, expected error/empty path, contracts, blast radius, test
co-modification, docs and cleanup; persist proof with concrete file/line failures.
Binary PASS/FAIL only, no conditional pass; informational path warnings do not
change verdict. Missing final structured verdict is failure.

Read [path tracing](../runtime/agents/tester/path-tracing.md) before tracing
exports/runtime/consumers/E2E, [test selection](../runtime/agents/tester/test-selection.md)
before tests, and [regression detection](../runtime/agents/tester/regression-detection.md)
for no-regression ACs. All AC-listed/matching changed-command tests and selected
tests must pass. Scope by risk/project commands and dependent callers; explain
exclusions, broaden for shared/core/schema risk, and never treat equal failure
totals as regression proof. Unexpected untracked test artifacts are a leak/FAIL.
The current selection owner does not grant a blanket documentation-only waiver.

Conduct externalizes the complete relevant diff above300 lines to captured file
plus `--stat`; at/below300 it inlines the whole diff. Task-start and retry diffs
stay distinct; Tester reads actual file for detail. Budget reserves reporting
before exhaustion; use foreground watcher continuation, not a detached atomic
turn. Project QA plans materialize cases at declared workflow transitions.

Browser execution selects unsatisfied non-waived browser-check/browser-inspection
cases and immutable method_config, then `yoke qa case run` with resolved URL,
expected branch and deployed HEAD SHA. Missing freshness/runner failure is not
review evidence; inspected undetermined outcome waits for owner/operator. The
runner records artifacts/verdict; no rewritten case or parallel manual Browser run.
Real E2E uses deployed backend and BASE_URL, after unit/integration success;
requires both URL and command, otherwise skip with reason. E2E failures are FAIL
even if units pass, with failing tests/errors/screenshots/traces/videos. Mocked
Browser integration belongs to full, shallow real-stack smoke to smoke.

### QA Walker

Walk one mission sequence chosen at runtime as an informed subagent or target-
naive session. Main retains item/Progress Log/human-request/report/final verdict.
Walker returns ranked findings and unverified areas; its turn is atomic.
Permission dialog, interactive sign-in or approval returns `WALK_STATUS: HUMAN_GATE`
with exact needed action/resume state, no Fleet mail. Main records handoff, routes
to live covering steering or human owner and dispatches a fresh walker;
acknowledgement is not sign-in proof. Discard routine screen perception, attach
only deliberate finding proof within runtime artifact limit. macOS window-server/
login-keychain commands use Terminal GUI-session bridge; display failures,
audit-session denial and misleading SSH OAuth expiry are wrong-session signals.

### Simulator

Read-only plan simulation checks architecture before sync; integration checks
actual code before merge. Verify FR coverage, contracts/construct shapes,
visibility, dependency order, environment assumptions and error boundaries.
Actual-code mode additionally verifies exports/names/merge sequence/review proof.
Inventory/prioritize reads within context budget; missing producer/consumer
type/signature/config consistency is CRITICAL, error-path mismatch WARNING.

Begin with `SIMULATION: CLEAN` or `SIMULATION: GAPS FOUND`, then exact
`EPIC: PREFIX-N` or `SCOPE: SYSTEM`. Machine prefixes `[CRITICAL]` block, `[WARNING]`
should fix, `[NOTE]` informs. Each gap classifies fix_level plan/code/mixed;
shared [auto-fix loop](../.agents/skills/yoke/simulate/autofix-loop.md) owns
classification, three Architect iterations and code-bearing amend routing.
Use registered readers, never direct DB clients; test side effects use isolated
fixtures/dry-run (`YOKE_DRY_RUN=1` where a source script may call GitHub).

System-wide Ouroboros audit is source-checkout-only, with five categories:
stale agents, stale skills, cross-agent assumptions, stale hooks and rule/runtime
contradictions. [System owner](source-dev/system-simulation.md) governs the source
guard and scope; no automatic system fix.

### Boss

Review one scope=spec|prd|plan against the supplied rubric and pinned transition.
Return exactly one READY/NOT_READY/CAVEATS verdict; parent parses/persists
shepherd_verdicts, Boss never calls shepherd verdict or writes source. Self-read
current item fields/body through registered commands even if caller inlines
content. Plan scope is Shepherd epic planning, not assumed issue/bug artifacts.
Verify FR Traceability covers every explicit FR: missing/unmapped gives NOT_READY;
spec without FR notation may receive softer CAVEATS. Respect agreed scope and
return actionable contradictions/completeness/naming/quality findings.

## Hook ownership and execution safety

[Subagent hook composer](../packages/yoke-core/src/yoke_core/domain/agents_render_subagent_hooks.py)
injects six Bash-capable Claude roles' hooks. PreToolUse is one matcherless
`yoke hook evaluate PreToolUse`, with role/config-owner identity; universal chain
selects guards by tool_name. PostToolUse/PostToolUseFailure use role-attributed
observe; SubagentStop uses agent_stop. This includes Boss. PM/Designer retain
their sidecar hooks; all eight have reflection/stop observation. Read actual
generated frontmatter rather than reproduce per-tool choreography here.

`agent_stop` is an item-lane auto-commit safety net and HarnessSessionStopped
telemetry; it neither drains claims nor completes a task. Safety-net/rescue is
not valid clean submission. The live shared hook registry owns SQL/shell, denied
Write/Edit, subagent backgrounding and telemetry ordering; stable audit id
lint-sqlite-cmd remains compatible with history. Hooks are Python-owned.

All six Bash role prompts prohibit nested Claude CLI and use native dispatch.
Runtime `lint_nested_claude_cli` evaluates requesting harness identity (relayed
executor, not server process): Claude-family nesting refused; Codex/Cursor first
session allowed; solely -h/--help/--version sessionless invocations allowed;
unknown ancestry refused. Operator-attended local canary may set
`lint_db_cmd_nested_claude_cli=warn`; remote SSH smoke exception is independent
`lint_db_cmd_remote_claude_cli=warn` (remote refusal lint-remote-claude-cli).
Neither weakens the DB-command guard. Skill dispatch authorization still binds.

## Packet compositions

Canonical Bash roles carry DB-PACKET topic marker pairs; renderer expands them
through schema_api_context. Explicit `yoke packets render --role R --topic T --detail full`
retains full schema/nested shapes/catalog/drift notes before
diagnostic SQL. Startup points to reads; no duplicate hand-authored cheat sheet.
`yoke agents render check` validates marker syntax, seed/live and adapter parity.

| Role | Current ROLE_TOPICS |
|---|---|
| main_agent | core, claims, auth, qa, packs; project depth pointer |
| engineer_agent, tester_agent, qa_walker_agent | core, claims, qa, project |
| architect_agent, simulator_agent, boss_agent | core, claims |

Authority is `schema_api_context_seed.ROLE_TOPICS`, not this snapshot. Main QA
recipes support case/run/tester-review inspection before re-dispatch. Engineer
progress/submission/verification, Tester review/verdict, Main/Architect authoring
coordination are needed at action; Boss/Simulator read, QA Walker follows mission.
Lifecycle repair, raw SQL, Pulumi state migration and expanded delivery remain
explicit topics. Retained startup recipes also exist in full depth.
PM/Designer have no Bash/packet section; a future Bash grant adds role topic key
and markers, not another cheat sheet. `harness_contract` is the manifest audience
layer, not a schema_api_context role: [bootstrap](harness-bootstrap.md).

Reviewed-implementation gate is authoritative: preview
`yoke qa gate-summary --item PREFIX-N --target reviewed-implementation`, then Main's registered
`yoke lifecycle transition PREFIX-N --to reviewed-implementation`. Direct status
writes are rejected even after tests pass; Engineer reads QA depth when required.

## Filing, continuity and reflections

Interactive/ad hoc filing uses `/yoke idea`: duplicate search, workflow and
authorized typed entry, GitHub sync and full structured content. Workflow-owned
bulk import/curate/simulation-gap filing may use their governed noninteractive
path with explicit project/workflow/authorized harness_skill and immediate full
definition. Dispatched roles report discovered issues to parent via reflections,
notes or final result; parent files through Idea. No harness task suggestions.

Claude subagents obey configured300-turn ceiling; inline Shepherd/Conduct carry
the segment without that subagent ceiling. Reserve role-specific reporting time:
read-only roles end with complete report, Engineer commits/submits, QA Walker
returns status/mission report. Absolute paths/active claims own access; independent
calls anchor git/test/source paths. Durable current-state checkpoints retain
live decisions/holds/blockers/actions and evidence links without historical essays.

**All agents use hook-captured reflection semantics.** Answer four questions:
problems, process improvements, game-changing ideas and cross-critique. Use
`---REFLECTION-START---` / `---REFLECTION-END---`, each entry delimited by
`---BEGIN ENTRY---` / `---END ENTRY---`, categories problem/friction/idea/cross-critique.
The PostToolUse Agent-tool hook (`yoke_core.domain.reflection_capture_hook`)
captures final output into ouroboros_entries. No agent writes directly to the DB.
Role phase owner/shared Pre-Submit Checklist governs exact shape and timing;
Tester reflection precedes its mandatory final binary verdict. `/yoke curate`
clusters/promotes/files observations from DB; no filesystem reflection log.
