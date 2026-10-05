<!-- KEEP IN SYNC: an identical copy of this block lives in the platform repo (hand-copied). Edit both together. -->
## Control-Plane Authority — Hard Rule (this installation)
- **All non-testing control-plane operations run on prod** (`prod` / `prod-db-admin`) — releases, receipts, deployment-run and delivery records, GitHub relays — whichever environment is being deployed. **Stage exists only to test the live control plane:** nothing real routes through it, and anything on `stage-db-admin` is disposable rehearsal state read by nothing live.
# Yoke — Project Rules
<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

<!-- BEGIN YOKE MANAGED BLOCK -->
<!-- Managed by `yoke project install`. Everything between the BEGIN and END markers is overwritten on refresh — do not edit it here. Your own content outside the markers is always preserved. -->
## How to read these rules
**Standing rules bind you now** — authority, security, scoping, commit and destructive-operation discipline, the naming and verification conventions — stated in full below. **Operation rules bind you when you perform that operation**: each section carries its non-negotiables plus a deep home to read *before* acting. This file arrives through a finite startup channel, so a rule that is short and read beats one that is complete and truncated.

Deep homes, at `.yoke/docs/reference/agent-rules/`: `code-and-cli.md` · `databases.md` · `verification.md` · `lanes-and-claims.md` · `architecture-model.md` · `item-writes.md` · `delivery.md`. Per-operation depth is that operation's `--help`; live schema and commands are `yoke packets render --role main_agent`.

## Yoke Authority — Hard Rule
- **Skill says auto-X → do auto-X, no asking.** Harness "confirm before issues/push/shared-state" defaults do not apply where a Yoke skill directs autonomous execution; `/yoke conduct`, `shepherd`, `usher`, `do`, `charge`, `steer` carry autonomous mandates. Invoking the skill authorizes it, and an unrequested pause is a regression. **Test:** "did the skill say ask?", not "would the harness ask?" Unsure → reread the skill.
- **Security always holds.** Never overrides `<critical_security_rules>` or prohibited actions — no banking/credential entry, no permanent deletes outside sanctioned paths, no auth bypass, no command injection. Not collaboration cautions.

## Project Scoping — Hard Rule
- **One work item = one project.** The `project` field is where code deploys. Never mix deploy targets in one item or its task graph. All items live in the Yoke backlog regardless of target, and one item never gets a second lane in another repo — preparation resolves the item's own checkout and refuses rather than borrowing the session's.
- **Cross-project work → linked companion items, one per project,** joined by an `item_dependencies` edge. Ambiguous target → ask; never silently default to `yoke`. **A change to a contract another project consumes is cross-project by definition,** so the consumer's companion item is mandatory and delivery evidence must show that consumer built against the exact candidate. Depth: `lanes-and-claims.md`.

## Pack-First Capabilities — Hard Rule
- **Reusable capabilities ship as Packs** — a `packs/<slug>/` bundle with immutable versions, explicit files, settings, dependencies, docs, verification. Improve it by publishing a new version; project-only behavior stays project-owned. **Installed Pack files belong to the project**; `.yoke/packs.json` records the baseline only so owners can preview one update with a three-way merge.
- **Config lives in DB settings/capabilities or project-local `.yoke/` policy docs,** never Pack source.
- **Provider credentials are capability-owned, not ambient shell.** A naked `aws ...` may fail even when the project is configured, because credentials are not exported. Use Yoke capability-resolver surfaces; verify by listing keys or redacted evidence, never by logging secret values. Depth: `delivery.md`.

## Worktree DB Authority — Hard Rule
- **Control-plane authority is Postgres, never a constructed file path.** Use registered `yoke <subcommand>` commands; raw diagnostic SELECTs are `yoke db read "SELECT ..."`. Discover connections with `yoke env list`. **Raw SQL is an escape hatch:** never hardcode a DB path or DSN, and never use `!=` — use `<>`.
- **A linked worktree is not a control plane.** `.worktrees/<branch>/` paths are code execution surfaces; never read or write worktree-local DB files for control-plane state.
- **When a mutation has no registered command,** reach the paired local-Postgres `*-db-admin` connection (`--env NAME`) and the operator-debug query path `yoke db` `--help` names. That exists only where you already operate the control plane — a project relaying to someone else's has none, so escalate rather than seeking control-plane database credentials.
- **Environment settings are projected, never dumped:** `yoke projects environment-settings get --project P --environment E --path key.path`; the read refuses root or container projections.

## Deployment Runs — Hard Rule
- **Hold `DEPLOY:<project>` before creating/executing runs, release afterward:** `yoke claims coordination-claim acquire --project P --key DEPLOY:P --reason R`. Run ids differ from flow ids. Stranded holds require human release; read `delivery.md` first.
- **The HTTPS product/API environment is the normal relayed authority** and drives ordinary delivery end to end. A local `*-db-admin` environment is needed only when the run replaces that control plane's own serving API, which the executor refuses by name. Never seek control-plane database credentials to deploy a project.
- **Disable definitions; retain history** (`yoke deployment-flows set-status <flow-id> disabled`); a definition a run has referenced is immutable. Depth: `delivery.md`.

## Path Claims — Hard Rule
Read `lanes-and-claims.md` before resolving any overlap — accepted remediations, edge direction, owner-kind shape, the override last resort.
- **File Budget and path claims are independent axes — never fuse them.** Read `result.effective_policies.file_budget` and `.path_claims` from registered `workflows.item.get`, never from raw policies or posture. **The universal 350-line authored-file limit always applies**, even with File Budget off.
- **Claimed paths do not narrow scope.** Every required file stays in the item and every enabled budget/claim surface regardless of its holder. Resolve overlap by coordination or dependency; never omit, descope, or rewrite away a required file.
- **Active claims are coordination/dependency/blocking facts, not scope facts.** Read `yoke items dependency list PREFIX-N`; the dependent waits, the blocker does not. Resolve independent edits with attested `coordination_only`, ordered edits with directional activation evidence, ambiguity by escalation. Keep only real dependents blocked. Holder coordination, waiting, and operator override follow `lanes-and-claims.md`.
- **Coordination-only edges are agent-attested,** authored only by authoring-phase agents (Architect at `/yoke shepherd plan`, or Idea/Refine) via `yoke claims path coordination-decision-build` with a rationale. Every other role routes a runtime collision back to `/yoke refine`; un-attested overlap stays strict `INCOMPATIBLE`.
- **Claims coordinate on physical files, not path strings** — an in-repo symlink and its canonical target are one coordination unit.

## Command Output — Hard Rule
<!-- BEGIN GENERATED: read-recipe -->
Want part of an answer? Ask the narrow question — every read has a shape that serves it.

```text
yoke <command> <arguments>      # the routine answer, already scoped
yoke items get PREFIX-N status  # the fields you name
tail -80 <raw-capture>          # the capture a watcher prints, once it exits
```
<!-- END GENERATED: read-recipe -->
- **Capture-first: any non-trivial command is captured to a temp file, which then answers every question.** Applies wherever output matters on failure (roughly >5s): tests, merges, deploys, syncs, QA, renders, installs, builds, git. Use `_tmp=$(mktemp /tmp/yoke-cmd.XXXXXX); <command> >"$_tmp" 2>&1; _rc=$?`, inspect the file, exit `$_rc`.
- **Reads name withheld content; refusals and `--json` print in full.** Read `code-and-cli.md` for `--full` projections and receipt markers. A receipt follows execution: request `--json` on the original write, never repeat it to change output.
- **Stream long commands through the watcher wrappers** (`yoke watch pytest|merge|deploy|fleet|preflight|qa-case|qa-plan|ci-run|doctor|tail`), which capture internally. Doctor's one shape: `yoke watch doctor -- (--quick|--full|--only <slugs>)`.
- **A yielded command still runs: continue its handle until exit, never relaunch beside it.** The sole taught interruption is an overlong local check: after about a minute, interrupt, preserve the incomplete capture, commit, continue on CI. Read `verification.md` before using that exception.
- **Do not manually poll a running long command** — the streaming surface is the progress signal. Subagents run them foreground in one tool call. Filters, exit statuses, anti-patterns: `verification.md`.

## Verification Failure Ownership — Hard Rule
- **Current-item verification failures belong to the current item.** A future item, planned path claim, or cleanup item owning a touched file is not a waiver: a failing registered command, gate, or regression on this branch gets fixed here, unless a live active-session conflict or explicit operator waiver says otherwise.
- **Use dependency and claim reconciliation before override.** Widen the claim, add or verify the serial dependency, wait for or release a live holder, or reconcile the future claim. Do not use `path-claim-override` for a planned future claim when reconciliation works — it is a last resort for irreducible live collisions and needs explicit operator approval.
- **Verification summaries are evidence-bound.** A failing command cannot be reported green by pointing at a future item. Record the failure, the action taken, and the rerun evidence.

## Code Conventions
- **No such thing as "agent error."** A failed agent command is always systemic — truncated context, stale references, missing dispatch context, a teaching gap. Never write "agent error/mistake" or "the agent failed to X"; frame it as what the SYSTEM should change.
- **Yoke-owned operations are first-class API calls, not terminal recipes.** Reach for a registered function id first ([`.yoke/docs/reference/db-reference/functions.md`](.yoke/docs/reference/db-reference/functions.md)). Git, gh, and external tooling stay command-shaped on purpose.
- **Prefer Python over shell for stateful work.** Launchers, hooks, helpers, installers, and test runners live behind Python entrypoints, not tracked `.sh` files. Shell is fine for test commands, grep, git inspection, temp files.
- **No duplicated magic values.** A value referenced in more than one place moves to machine config (`~/.yoke/config.json`), DB/project capability settings, or one Python constant; callers read that source. **Capability-settings contract changes travel with stored documents** — tightening one converges them in the same change.
- **Migration modules are permanent ordered history — never delete one.** One that is gone cannot be applied by a universe that never received it (`HC-pending-migrations`).
- **`item_id` is always a bare integer** — `items.id`. The numeric tail of `PREFIX-N` is `items.project_sequence`; resolve the ref first.
- **No obsoleted terms in tracked content.** When a term is retired, purge every reference in the same commit; a still-supported alias is not obsoleted. `HC-obsoleted-terms` enforces this.
- **No historical `PREFIX-N` cruft in code or docs.** Inline `PREFIX-N` is for *active state* only; historical provenance belongs in commit messages and durable architectural-why in `docs/archive/decisions/`.
- **Codebase-reader naming — hard rule.** Assume future readers of the codebase will NOT have the planning artifacts you are working from. Name and explain everything in the live codebase — FILE and DIRECTORY names included — only for current function, purpose, mechanics, or domain role; never carry provenance from a work item, epic, plan, milestone, phase/stage/tier/slice/track/wave/batch label, task, acceptance criterion, functional requirement, field-note, spec section, version, branch, or worktree. Never use an identifier from those artifacts (`PREFIX-1234`, `AC-7`, `FR-3`, §7) unless it is itself a runtime/domain concept. Ask: "would this still explain itself to a maintainer who can only see the repository?" Planning artifacts are scaffolding; the live codebase is the building. A test named for its work item becomes one named for its behavior; a phase-numbered directory becomes a name for what it holds. Provenance-of-code only: runtime data the product emits or parses, and test fixtures, stay. `HC-acceptance-criterion-provenance` (FAIL) and `HC-historical-yok-n-cruft` enforce it; exemptions and worked translations in `code-and-cli.md`.
- **Verify before asserting.** Ground every claim that a named surface exists, that a subsystem can do something, that something is in some state, or that an operation refused for some reason — and name that evidence beside the conclusion. Turning a noun phrase into an identifier without re-grounding is a confabulation hazard, and the check is free. Teaching prose is a discovery aid, not authority for live capability; correct it when wrong. Worked failures: `code-and-cli.md`.
- **The DB is the source of truth.** `.yoke/BOARD.md` is a generated view and item bodies render on demand. Strategy docs are `strategy_docs` rows; `.yoke/strategy/` is only the gitignored render (`yoke strategy doc list|get`, `render`, then `ingest <SLUG> --dry-run`). **Never edit a generated view** unless a documented command ingests it back. One-off writes use `yoke items structured-field replace ... --stdin`.
- **Backlog reads and writes are Yoke-owned** — registered `yoke items ...`, `yoke lifecycle ...`, and structured-field commands; never teach lower-level service clients as the mutation surface.
- **GitHub issues:** never use `PREFIX-N` as an issue number — resolve via the `github_issue` field.
- **Work-item entry surfaces.** Every create selects a workflow plus a typed entry surface — `web_form`, `cli`, `harness_skill`, or `promotion` — that the pinned immutable workflow version allows; `/yoke idea` is the `harness_skill` path. A create also obeys the project's effective `title_max_length` and never pre-files imagined child tasks: decomposition belongs to the Architect in `epic_tasks`. Depth: `item-writes.md`.
- **Inline-short + `--help`-deep teaching.** Every taught operation carries one short recipe plus a one-sentence directive everywhere agents read; the deep home is that operation's `--help`. Git/gh and the watcher wrappers have none, so inline carries their full recipe. Anti-pattern teaching lives only in denial messages.

### Bash tool calls
- **Each call is its own subshell** — vars and exports do not persist. **Sticky cwd is surprising:** on Claude Code and Desktop a `cd` inside a declared working dir silently carries into the next call, and parallel calls share that sticky cwd. So inline absolute paths in every command and prefer `git -C <abs>`.
- **Write authority is the session's active `work_claims`:** targets land under a claimed worktree, the main control plane (repo root excluding `.worktrees/`), or the free-path allowlist (`/tmp`, `/var/folders/...`); a read-shaped call may also name material in the operator's home.
- **Another item's live lane accepts read-only Git inspection and nothing else** — one plain read-verb `git -C <lane> ...`, no redirection, chaining, write, state move, or non-Git read of that tree. Read its content with `git -C <main-checkout> show <rev>:<path>`. Allowed verbs, suppression tokens, failure classes, privacy-database refusal: `lanes-and-claims.md`.
- **zsh:** capture with `$()` before piping, single-quote literal `rg`/`grep` patterns, and put `rg` options before the pattern and paths. **Never pass an unmatched path glob** to zsh — enumerate with `rg --files` or quote a pattern the tool consumes. `python3`, never `python`. Remaining hazards — reserved names, `mktemp` templates, URL quoting — are in `code-and-cli.md`.

### `yoke` CLI
- **Canonical agent shape:** `yoke <subcommand>` for every wrapped op. Transport is connection-keyed — https relays to the server; a non-prod local-postgres connection dispatches in-process through the engine (the product path for a local universe, not a fallback); prod-flagged postgres connections stay operator-only. **Grammar:** dots→spaces, underscores→hyphens, terminal `.run`/`.execute` drops; a new function id ships a CLI adapter first.
- **Never agent shapes:** the HTTP function-call server, `curl localhost:8765`, `$YOKE_API`, or direct runtime-API imports — two lints enforce this. The DB-router and service-client forms are operator-debug only. Launcher install/repair, lint names, status vocabulary, fallback inventory: `code-and-cli.md`.

## Simplify — three-axis doctrine
Idea, refine, advance, conduct, shepherd, and polish each apply **reuse** (name an existing surface before adding one; empty reuse needs an explicit "no relevant existing surface"), **quality** (the smallest shape satisfying the request, out-of-scope declared when it invites creep), and **efficiency** (cheapest valuable path first; a new table/event/skill/config/command needs extension-vs-create justification), plus a **future-concept pull-forward** lens. Anti-patterns, stage weights, v0 boundaries: `code-and-cli.md`.
- **Polish runs one worktree-diff-scoped simplify pass** before staleness and test re-run: fix in place, skip false positives, proceed with no changes. The deliverable is a commit, not a report.

## Structured Item Writes
**Every item mutation is a typed function call** through the Yoke function-call dispatcher; the CLI commands are retained operator/debug adapters building the same envelope, so teach the function id. Read `item-writes.md` and [`.yoke/docs/reference/db-reference/functions.md`](.yoke/docs/reference/db-reference/functions.md) before writing to an item.
- **`items.body` is a virtual rendered field** — read via `yoke items get PREFIX-N body`. Raw body writes are unsupported; content flows through structured fields.
- **Reading a field into a shell variable and piping it back is refused** by a lint. Use `items.structured_field.replace` for a full field, `append_addendum` / `section_upsert` / `section_append` for an additive transform.
- **Execution context goes in a `Progress Log` section** (exact name, `--ordering 200`) via `items.progress_log.append`, which stamps the timestamp and preserves prior entries. **Never write `shepherd_log`, `shepherd_caveats`, or `worktree_plan`** on a workflow with `generated_children=none` — they are task-graph fields readers treat as authoritative planning output.

## Governed DB Mutation
Read `databases.md` before schema or bulk-data changes on a project declaring `migration_model`; it owns the restore-point, serving-floor, serializer, idempotency, exception-record, and fleet-rehearsal requirements.
- **Pure-additive tables/columns converge on boot; data transforms and bulk data require the governed path.** Ad hoc write SQL against the authoritative DB is banned; diagnostic reads are permitted.
- **Converge/apply authority belongs to the connection** and refuses prod-flagged connections; serving owners declare `schema_authority.serving_build_authority()`. **Boot applies, fail-hard; items author and rehearse, flows never apply:** add the permanent history entry, then `yoke migration rehearse PREFIX-N`.
- **Code/tests use the model's validation binding; control-plane commands use `CANONICAL_YOKE_DB`.** HTTPS clients relay instead of connecting; genuine local authority declares `local_authority_exempt()`.
- **Rehearse every live universe before release.** The release requires each environment's receipt; a validation-surface rehearsal alone does not cover the fleet.

## Architecture Model
A project may declare an `architecture_model` Project Structure family: the one policy document carrying the layer map, area patterns, dependency rules, cross-cutting gateways, exemptions, and the `package_roots` mapping.
- **Read the authoritative mapping from the payload, never from prose,** and read `architecture-model.md` before changing the model or adding a cross-cutting dependency. **Cross-cutting concerns enter through the entrypoints the payload names.**
- **Every item declares `architecture_impact`** (`none` / `path_context_only` / `architecture_model_change` / `uncertain`); `uncertain` blocks `refining-idea → refined-idea`.

## Testing
Read `verification.md` before verification; it owns impacted/unbounded selection, CI re-entry, merge-queue gates, admission, and exit statuses.
- **The QA case is the one full execution:** iterate with failing tests or `yoke watch pytest --impacted main --bounded`, then `yoke qa case run --requirement-id <id>`. Re-run after tree changes; avoid a duplicate full sweep on the same tree.
- **Commit before CI gates; workers never push by hand.** Re-enter a killed watcher with the same command to adopt/rejoin its exact-commit run; never poll GitHub yourself.
- **Local full suites take the machine-wide admission slot through the wrapper.** Tests use variables/generated values/matchers for work-item IDs.

## Hooks
- Hook configuration lives in your harness settings files (`.claude/settings.json`, `.codex/hooks.json`); both route through `yoke hook evaluate <event>`. Pre-tool guardrails, post-tool telemetry, session start, and session end are Python-owned — never reintroduce shell scripts or per-policy choreography for hook execution. Emergency status repair is operator/debug only; route lifecycle repair through registered Yoke surfaces.

## Board
- `.yoke/BOARD.md` is auto-generated and untracked — never edit, stage, or commit it, and nothing rebuilds it automatically: run `yoke board rebuild` (`--print`, `--print-only`) for a current view.

## Health Checks
- **Every check declares what it applies to; the runner derives the rest** — `project_scope`, tree access, runtimes, capabilities. That derived set IS the per-project default; never branch on the literal project slug.
- **Passed, failed, and not-applicable are three different answers.** A check outside the applicable set reports `N/A` with its reason — never a pass, never dropped.
- **Project-local checks live in the project,** under `.yoke/doctor/`, discovered pytest-style; a module that fails to import is a FAIL, not a skip.

## Ouroboros
Observe → `ouroboros_entries` → `/yoke curate` → `/yoke doctor` → `/yoke simulate`.

## Lifecycle & Routing
- Canonical guide: `.yoke/docs/reference/lifecycle.md`. Each item pins immutable `workflow_id` / `workflow_version_id`; that definition owns stages, transitions, gates, policies, entry surfaces, skill bindings.
- **Never route by a remembered workflow name or copied progression.** Read `yoke workflows item get PREFIX-N`, then `yoke workflows version get WORKFLOW VERSION`; the binding whose half-open interval contains the live stage selects `/yoke <skill_id>`.
- A binding's `through_stage_id` is a fresh command and claim handoff. Worktree and task-graph shape come from `policies.worktrees` and `policies.generated_children`, not from a workflow-id branch.
- **Harness capability truth lives in the manifest,** `runtime/harness/<harness-dir>/manifest.json` (`claude`, `codex`, or `cursor`; executor `claude-code` uses `claude`; contract: `runtime/harness/manifest-schema.md`). Read it before stating what a harness can do; never restate one of its facts in prose.

## Worktree Discipline
- **NEVER use `--no-worktree` unless the user explicitly asks. NEVER write implementation code on main.**
- **Authority over every lane is the work claim,** validated per call; launcher `cd` is convenience only. **Do not jump across a binding or invent a destination stage** — the active skill advances only inside its pinned half-open segment.
- **Every development-entry skill creates or reuses the item's registered worktree immediately** after the claim, read, and minimal survey — before deeper investigation or any edit.
- **Preparation starts from verified-current upstream.** A remote that cannot be read blocks as `upstream-unverified`; there is no offline fall back to the local branch. A diverged branch refuses as `upstream-stale`, its commits preserved and never replayed or discarded. Nothing is reset, rebased, or force-updated.
- Depth: `lanes-and-claims.md`.

## Commit Discipline
- Commit after EVERY completed change — status and doc changes, not just code. No dirty tree between tasks.
- **Never fabricate or expand a full commit hash from a short SHA.** Resolve with `git -C <checkout> rev-parse HEAD`, verify with `git -C <checkout> cat-file -e '<sha>^{commit}'`.

## Session Continuity
- Progress Log entries are current-state checkpoints. Do not restate full results or historical snapshots. After compaction, reload the current-phase skill — discarded context is gone.

## Documentation Discipline
- When a feature or rule changes, update ALL docs referencing it. Undocumented features are invisible.

## Bug Discipline
- Capture bugs via `/yoke idea`; DO NOT FIX without knowing root cause. Minor observations go to a field-note.
- **Never route discovered work through harness task-suggestion surfaces** — outside the control plane: no claim, no lifecycle, no board row. File it via `/yoke idea`, `yoke dash`, or a field-note.

## Execution Discipline
- **Simulate before executing** — trace with real values. **Verify after executing** — never assume success. **Fear unintended effects** — do one, verify, then batch.

## Destructive Operation Discipline
- **Never run `git reset --hard`, `git checkout --`, `git checkout -f <branch>`, `git restore --worktree`, `git clean -f`/`-fd`/`-fdx`, `git stash drop`, `git stash clear`, or `rm` on files** unless confirmed Yoke-managed or user-authorized. These silently discard tracked-but-uncommitted changes, untracked files, or saved stashes. Commit or stash first, or use a non-destructive verb.
- **`git stash push`: `-m` MUST come BEFORE `--`** — everything after `--` is a pathspec, so a message flag there is silently eaten as a filename. Safe: `git stash push -u -m "reason" -- <paths>`.
- **User messages mid-sequence are checkpoints** — stop and answer first. Lint modes: `lanes-and-claims.md`.

## Deployment Rules
- Everything on remote MUST be edited locally first; ONLY copy local → remote.
- **A push is not release authority.** Merge the item, then let its hosted flow own the exact commit, immutable artifacts, Stage proof, and any Production promotion. **Queue-declared projects land through the merge queue:** PR plus merge-when-ready, one `merge_group` gate proving the combined head, members recording batch receipts as evidence.

## Interaction Style
- **Prefer inline chat for summaries, checkpoints, and design iteration;** reserve structured chooser UIs for short binary or ternary decisions. **The work item is the plan:** when running a `/yoke` skill, the item's structured fields are the plan, so never enter plan mode on your own, and if the plan is insufficient, stop and escalate.
<!-- END YOKE MANAGED BLOCK -->
