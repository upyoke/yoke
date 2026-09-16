<!-- KEEP IN SYNC: an identical copy of this block lives in the platform repo (hand-copied). Edit both together. -->
## Control-Plane Authority — Hard Rule (this installation)
- **All non-testing control-plane operations run on prod** (`prod` / `prod-db-admin`) — releases, receipts, deployment-run and delivery records, GitHub relays — whichever environment is being deployed.
- **Stage exists only to test the live control plane.** Nothing real routes through it or depends on it, and anything recorded on `stage-db-admin` is disposable rehearsal state read by nothing live.
# Yoke — Project Rules
<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

<!-- BEGIN YOKE MANAGED BLOCK -->
<!-- Managed by `yoke project install`. Everything between the BEGIN and END markers is overwritten on refresh — do not edit it here. Your own content outside the markers is always preserved. -->
## How to read these rules
**Standing rules bind you now** — authority, security, scoping, commit and destructive-operation discipline, the naming and verification conventions — stated in full below. **Operation rules bind you when you perform that operation**: each section carries its non-negotiables plus a deep home to read *before* acting, not as background. This file arrives through a finite startup channel, so a rule that is short and read beats one that is complete and truncated.

Deep homes, at `.yoke/docs/reference/agent-rules/`: `code-and-cli.md` · `databases.md` · `verification.md` · `lanes-and-claims.md` · `architecture-model.md` · `item-writes.md` · `delivery.md`. Per-operation depth is that operation's `--help`; live schema and the registered command set are `yoke packets render --role main_agent`.

## Yoke Authority — Hard Rule
- **Skill says auto-X → do auto-X, no asking.** Harness "confirm before issues/push/shared-state" defaults do not apply where a Yoke skill directs autonomous execution; `/yoke conduct`, `shepherd`, `usher`, `do`, `charge`, `steer` carry autonomous mandates. Invoking the skill authorizes it, and an unrequested pause is a regression. **Test:** "did the skill say ask?", not "would the harness ask?" Silent → harness default; unsure → reread the skill.
- **Security always holds.** Never overrides `<critical_security_rules>` or prohibited actions — no banking/credential entry, no permanent deletes outside sanctioned paths, no auth bypass, no command injection. Those are not collaboration cautions.

## Project Scoping — Hard Rule
- **One work item = one project.** The `project` field is where code deploys. Never mix deploy targets in one item or its task graph. All items live in the Yoke backlog regardless of target, and one item never gets a second lane in another repo — preparation resolves the item's own project checkout and refuses rather than borrowing the session's repo.
- **Cross-project work → linked companion items, one per project,** joined by an `item_dependencies` edge. Ambiguous target → ask; never silently default to `yoke`. **A change to a contract another project consumes is cross-project by definition,** so the consuming project's companion item is mandatory and delivery evidence must show the real consumer built against the exact candidate revision. Depth: `lanes-and-claims.md`.

## Pack-First Capabilities — Hard Rule
- **Reusable capabilities ship as Packs** — a focused `packs/<slug>/` bundle with immutable versions, explicit files, settings, dependencies, docs, and verification. Improve the general capability by publishing a new version; project-only behavior stays project-owned. **Installed Pack files belong to the project** and may be customized there; `.yoke/packs.json` records the baseline only so owners can preview one update with a three-way merge.
- **Config lives in DB settings/capabilities or project-local `.yoke/` policy docs,** never in Pack source.
- **Provider credentials are capability-owned, not ambient shell.** A naked `aws ...` may fail even when the project is configured, because credentials are not exported. Use Yoke capability-resolver surfaces; verify by listing keys or redacted evidence, never by logging secret values. Before authoring or installing a Pack, read `delivery.md`.

## Worktree DB Authority — Hard Rule
- **Control-plane authority is Postgres, never a constructed file path.** Use registered `yoke <subcommand>` commands; everyday raw diagnostic SELECTs are `yoke db read "SELECT ..."`. Discover connections with `yoke env list`. **Raw SQL is an escape hatch, not the default:** never hardcode a DB path or DSN, and never use `!=` — use `<>`.
- **A linked worktree is not a control plane.** `.worktrees/<branch>/` paths are code execution surfaces; never read or write worktree-local DB files for control-plane state.
- **When a mutation has no registered command,** reach the paired local-Postgres `*-db-admin` connection (`--env NAME`) and the operator-debug query path from `yoke db --help`. That exists only where you already operate the control plane — a project relaying to someone else's has none, so escalate the missing command rather than seeking control-plane database credentials.
- **Environment settings are projected, never dumped:** `yoke projects environment-settings get --project P --environment E --path key.path`. The read refuses root or container projections. Depth: `databases.md`.

## Deployment Runs — Hard Rule
- **One deploy lock per project; a flow id is not a run id.** Hold `DEPLOY:<project-slug>` before creating or executing a run (`yoke claims coordination-claim acquire --project P --key DEPLOY:P --reason R`), release after. A hold stranded by a dead driver clears only via the human-only `yoke coordination-claim release`. Run ids look like `run-YYYYMMDD-NNN`.
- **The HTTPS product/API environment is the normal relayed authority** and drives ordinary delivery end to end. A local `*-db-admin` environment is needed only when the run replaces that control plane's own serving API; the executor refuses that one case by name. Never go looking for control-plane database credentials to deploy a project.
- **Disable definitions; retain history** (`yoke deployment-flows set-status <flow-id> disabled`). A definition a run has referenced is immutable and undeletable. Depth: `delivery.md`.

## Path Claims — Hard Rule
Read `lanes-and-claims.md` before resolving any overlap — accepted remediations, edge direction, owner-kind shape, the override last resort.
- **File Budget and path claims are independent policy axes — never fuse them.** Read `result.effective_policies.file_budget` and `.path_claims` from registered `workflows.item.get`, never reconstructed from raw policies or posture. **The universal 350-line authored-file limit always applies**, even with File Budget off.
- **Claimed paths never narrow scope.** If the right fix touches a file, the file stays in the item and in every enabled budget or claim surface, whoever holds an overlapping claim. "Avoid the overlap" authorizes coordinating with the holder or recording a dependency — never a smaller scope artifact. Removing the required file is never an option.
- **Active claims are coordination facts, not scope facts.** `item_dependencies` rows are directional: the dependent waits, the blocker does not. Read them with `yoke items dependency list PREFIX-N`.
- **Coordination-only edges are agent-attested,** authored only by authoring-phase agents (Architect at `/yoke shepherd plan`, or Idea/Refine) via `yoke claims path coordination-decision-build` with a written rationale. Every other role routes a runtime collision back to `/yoke refine`. Un-attested overlap stays strict `INCOMPATIBLE`.
- **Claims coordinate on physical files, not path strings** — an in-repo symlink and its canonical target are one coordination unit.

## Command Output — Hard Rule
- **Capture-first: any non-trivial command is captured to a temp file.** Never pipe a live invocation into `tail`, `head`, or any truncating consumer — that discards failure context and masks the exit code. Applies wherever output matters on failure (roughly >5s): tests, merges, deploys, syncs, browser QA, renders, installs, builds, long git ops. Use `_tmp=$(mktemp /tmp/yoke-cmd.XXXXXX); <command> >"$_tmp" 2>&1; _rc=$?`, then inspect and exit `$_rc`.
- **Yoke's own adapters run bare.** Registry-covered commands (`yoke <subcommand>`, `db_router`, `service_client`) are short: run them bare, add `--json` for structure, never wrapped in redirection, pipes, truncators, or `| python -c` soup.
- **Stream long commands through the watcher wrappers** (`yoke watch pytest | merge | deploy | fleet | preflight | qa-case | doctor`), which capture internally. Doctor has one shape everywhere: `yoke watch doctor -- (--quick | --full | --only <slugs>)`.
- **A command that outlives its yield is still running — continue it, never relaunch it.** Every harness hands a long command back before it finishes; none of those handoffs is an interruption. Re-run only once the process is verifiably gone: a relaunch beside a live invocation spends the shared resource twice and can cancel the work the first was about to finish.
- **Do not manually poll a running long command** — the streaming surface is the progress signal. Subagents run long commands foreground in one tool call. Filters, exit statuses, anti-patterns: `verification.md`.

## Verification Failure Ownership — Hard Rule
- **Current-item verification failures belong to the current item.** A future item, planned path claim, or cleanup item owning a touched file is not a waiver: a failing registered command, gate, or regression on this branch gets fixed here, unless there is a live active-session conflict or an explicit operator waiver.
- **Reconcile before override.** Widen the claim, add or verify the serial dependency, wait for or release a live holder, or reconcile the future claim. `path-claim-override` is a last resort for irreducible live collisions and needs explicit operator approval.
- **Verification summaries are evidence-bound.** A failing command cannot be reported green by pointing at a future item. Record the failure, the action taken, and the rerun evidence that made it green.

## Code Conventions
- **No such thing as "agent error."** A failed agent command is always systemic — truncated context, stale references, missing dispatch context, a teaching gap. Never write "agent error/mistake" or "the agent failed to X" anywhere; frame it as what the SYSTEM should change.
- **Yoke-owned operations are first-class API calls, not terminal recipes.** Reach for a registered function id first ([`.yoke/docs/reference/db-reference/functions.md`](.yoke/docs/reference/db-reference/functions.md)). Git, gh, and external tooling stay command-shaped on purpose — that is the exception.
- **Prefer Python over shell for stateful work.** Launchers, hooks, helpers, installers, and test runners live behind Python entrypoints, not tracked `.sh` files. Shell stays fine for project test commands, grep, git inspection, and temp files.
- **No duplicated magic values.** A value referenced in more than one place moves to machine config (`~/.yoke/config.json`), DB/project capability settings, or a single Python constant; callers read the one source. **Capability-settings contract changes travel with stored documents** — tightening a contract converges them in the same change.
- **Migration modules are permanent ordered history — never delete one.** A module that is gone cannot be applied by a universe that never received it (`HC-pending-migrations`).
- **`item_id` is always a bare integer** — the internal `items.id`. The numeric tail of `PREFIX-N` is `items.project_sequence`; resolve the ref first.
- **No obsoleted terms in tracked content.** When a term is retired, purge every reference in the same commit; a still-supported compatibility alias is not obsoleted. `HC-obsoleted-terms` enforces this.
- **No historical `PREFIX-N` cruft in code or docs.** Inline `PREFIX-N` is for *active state* only; historical provenance belongs in commit messages and durable architectural-why in `docs/archive/decisions/`.
- **Codebase-reader naming — hard rule.** Future readers will NOT have the planning artifacts you are working from. Name and explain everything in the live codebase — file and directory names included — only for current function, purpose, mechanics, or domain role; never carry provenance from a work item, epic, plan, phase/tier/wave label, acceptance criterion, field-note, spec section, version, branch, or worktree. Ask: "would this still explain itself to a maintainer who can only see the repository?" Provenance-of-code only: runtime data the product emits or parses, and test fixtures, stay. `HC-acceptance-criterion-provenance` (FAIL) and `HC-historical-yok-n-cruft` enforce it; exemptions and worked translations in `code-and-cli.md`.
- **Verify before asserting.** Ground every claim that a named surface exists, that a subsystem can do something, that an item/session/claim/launch/deployment is in some state, or that an operation refused for some reason — and name that evidence beside the conclusion. Turning a noun phrase from an item, doc, or commit into an identifier without re-grounding is a confabulation hazard, and the check is free. Teaching prose is a discovery aid, not authority for live capability; correct it when it is wrong. Worked failures: `code-and-cli.md`.
- **The DB is the source of truth.** `.yoke/BOARD.md` is a generated view and item bodies render on demand. Strategy docs are `strategy_docs` rows; `.yoke/strategy/` is only the gitignored render — `yoke strategy doc list|get`, `yoke strategy render`, then `yoke strategy ingest <SLUG> --dry-run`. **Never edit a generated view** unless a documented command ingests it back. One-off writes use `yoke items structured-field replace ... --stdin`.
- **Backlog reads and writes are Yoke-owned** — registered `yoke items ...`, `yoke lifecycle ...`, and structured-field commands. Never teach lower-level service clients as the public mutation surface.
- **GitHub issues:** never use `PREFIX-N` as an issue number — resolve via the `github_issue` field.
- **Creating an item** selects a workflow plus a typed entry surface the pinned version allows, obeys the project's effective `title_max_length`, and never pre-files imagined child tasks — decomposition belongs to the Architect in `epic_tasks`. Rules and surfaces: `item-writes.md`.
- **Inline-short + `--help`-deep teaching.** Every taught operation carries one short recipe plus a one-sentence directive everywhere agents read; the deep home is that operation's `--help`. Git/gh and the watcher wrappers have no Yoke `--help`, so inline carries their full recipe. Anti-pattern teaching lives only in denial messages.

### Bash tool hazards
- **Each call is its own subshell** — vars and exports do not persist. **Sticky cwd is surprising:** a `cd` inside a declared working dir silently carries into the next call. So inline absolute paths in every command and prefer `git -C <abs>`.
- **Write authority is the session's active `work_claims`:** targets land under a claimed worktree, the main control plane (repo root excluding `.worktrees/`), or the free-path allowlist (`/tmp`, `/var/folders/...`). A read-shaped call may also name reference material in the operator's home.
- **Another item's live lane accepts read-only Git inspection and nothing else** — one plain read-verb `git -C <lane> ...`, no redirection, no chaining, no write or state move, and no non-Git read of that tree. Read its content with `git -C <main-checkout> show <rev>:<path>`. Allowed verbs, suppression tokens, failure classes, and the privacy-database refusal: `lanes-and-claims.md`.
- **zsh:** capture with `$()` before piping. Single-quote literal `rg`/`grep` patterns; put `rg` options before the pattern and paths. Never pass an unmatched path glob to zsh — enumerate with `rg --files` or quote a pattern the tool consumes. Quote URLs containing `?`. Never name shell vars `path` or `status` (zsh specials). `python3`, never `python`. `mktemp` templates must END in `XXXXXX`.

### `yoke` CLI
- **Canonical agent shape:** `yoke <subcommand>` for every wrapped op. Transport is connection-keyed — https relays to the server; a non-prod local-postgres connection dispatches in-process through the engine (the product path for a local universe, not a fallback); prod-flagged postgres connections stay operator-only. **Grammar:** dots→spaces, underscores→hyphens, terminal `.run`/`.execute` drops; a new function id ships a CLI adapter first.
- **Never agent shapes:** the HTTP function-call server, `curl localhost:8765`, `$YOKE_API`, or direct runtime-API imports. `lint-no-agent-runtime-api-import-from-c` and `lint-no-agent-curl-against-yoke-api` enforce this; the DB-router and service-client forms are operator-debug only. Launcher install/repair, status vocabulary, and the fallback inventory: `code-and-cli.md`.

## Simplify — three-axis doctrine
Idea, refine, advance, conduct, shepherd, and polish each apply **reuse** (name an existing surface covering the outcome before adding one; empty reuse needs an explicit "no relevant existing surface"), **quality** (the smallest shape that satisfies the request, with out-of-scope declared when the request invites creep), and **efficiency** (the cheapest valuable path first; a new table/event/skill/config/command needs extension-vs-create justification), plus a **future-concept pull-forward** lens. The named anti-patterns per axis, per-stage weights, and v0 boundaries: `code-and-cli.md`.
- **Polish runs one worktree-diff-scoped simplify pass** before staleness and test re-run: fix in place, skip false positives, proceed with no changes. The deliverable is a commit, not a report.

## Structured Item Writes
**Every item mutation is a typed function call** through the Yoke function-call dispatcher; the CLI commands are retained operator/debug adapters building the same envelope, so teach the function id. Read `item-writes.md` and [`.yoke/docs/reference/db-reference/functions.md`](.yoke/docs/reference/db-reference/functions.md) before writing to an item.
- **`items.body` is a virtual rendered field** — read via `yoke items get PREFIX-N body`. Raw body writes are unsupported; all content flows through structured fields.
- **Reading a field into a shell variable and piping it back is refused** by the structured-field-transform lint. Use `items.structured_field.replace` for a full field, `append_addendum` / `section_upsert` / `section_append` for an additive transform.
- **Execution context goes in a `Progress Log` section** (exact name, `--ordering 200`) via `items.progress_log.append`, which stamps the timestamp and preserves prior entries. **Never write `shepherd_log`, `shepherd_caveats`, or `worktree_plan`** on a workflow with `generated_children=none` — they are task-graph fields and readers treat them as authoritative planning output.

## Governed DB Mutation
Applies to any project declaring a `migration_model` capability. Before any schema or bulk-data change read `databases.md` — DB-claim workflow, the `breakage_policy` / `migration_strategy` gate matrix, compatibility classes, stranded-lease recovery. These bind regardless:
- **Pure-additive net-new tables and columns need no governed migration** — they self-propagate on the boot converge. **Data-transforming changes and bulk data go only through a governed path;** ad hoc write SQL against a declared authoritative DB is banned. Read-only SQL is always permitted.
- **Authority to converge or apply belongs to the connection, not the command** — both refuse on a prod-flagged connection. A process that genuinely serves or owns the database declares `yoke_contracts.schema_authority.serving_build_authority()` at the call site.
- **Applying is the boot converge's job** — no work item applies anything, no flow carries an apply stage, boot is fail-hard. A work item owes authorship and rehearsal: add the entry to the ordered history, then `yoke migration rehearse PREFIX-N` from a local-Postgres or db-admin connection.
- **Never apply a destructive migration without a named restore point** — the applier refuses otherwise. **An entry removing a surface declares `MINIMUM_SERVING_VERSION`; a new entry declares `"next-release"`, never a literal version.**
- **An entry that transforms rows must be idempotent against its own output already existing,** not merely against having already run — while it sits unapplied the running code can publish the very row it would produce. **One rewriting rows under a digest or immutability guarantee must use the same canonical serializer its readers use,** or it manufactures drift indistinguishable from corruption.
- **Implementation code and tests validate against the model's declared validation surface** (`model.runner.connection_env_var`); `/yoke` control-plane commands always use `CANONICAL_YOKE_DB`. Every audit-fingerprint exception call site needs a paired `docs/archive/decisions/<helper-name>.md` and a populated `exception_reason`.
- **Rehearsal against the validation surface proves nothing about the universes that need the entry.** Before releasing a build carrying an unapplied entry, run the fleet migration preflight over a throwaway copy of every live database and record its receipt; the release refuses before allocating its tag when an entry has no receipt for that environment.
- **Client-side code reaches control-plane rows by relaying, never by connecting.** Over https there is no local database; `db_backend.connect()` refuses with `RemoteControlPlaneConnectionError`, deliberately outside the `Exception` hierarchy. Genuine local authority declares `control_plane_locality.local_authority_exempt()` at the call site.

## Architecture Model
A project may declare an `architecture_model` Project Structure family: the one policy document carrying the layer map, area patterns, dependency rules, cross-cutting gateways, exemptions, and the `package_roots` mapping module resolution reads.
- **Read the authoritative mapping from the payload, never from prose,** and read `architecture-model.md` before changing the model or adding a cross-cutting dependency. **Cross-cutting concerns enter through the entrypoints the payload names;** never around them.
- **Every item declares `architecture_impact`:** `none` / `path_context_only` / `architecture_model_change` / `uncertain`; `uncertain` blocks `refining-idea → refined-idea`.

## Testing
Read `verification.md` before an item's first verification run — impacted selection, unbounded verdicts, merge-queue gating, CI wake delivery, exit statuses.
- **One canonical verification execution — the QA case run IS the final full gate.** Iterate freely while implementing with the single failing test and `yoke watch pytest --impacted main --bounded`. When ready, the **full** run happens exactly once, through the item's attached Command case: `yoke qa case run --requirement-id <id>`.
- **Never run a project's full sweep by hand and then re-execute the same tree through QA.** The gate re-runs the identical command, so the hand-run buys nothing while doubling compute and shared admission-queue pressure. Re-running after the tree changes is a different execution and stays required.
- **The gate runs where the project's suite already runs.** With `ci_workflow_file` declared, registered scopes bind to CI, so **commit before running the gate** — item branches stay local until then, and workers never push the lane by hand.
- **A gate whose watcher was killed did not lose its CI run.** It asks GitHub about the exact commit first — a concluded run there is adopted, one in flight rejoined, only an unexamined commit rebased. Re-run the same command; never poll GitHub yourself.
- **A quiet watcher is not a dead one.** Continue through your harness's continuation surface; re-run only once the process is really gone. Taught exception, for an overlong *local* check only: interrupt past a minute, keep the capture, commit, continue on CI.
- **Every local full-suite execution takes the machine-wide admission slot.** A bare `python3 -m pytest <dirs>` takes nothing and stays invisible to runs that queue politely; `lint-raw-pytest-full-suite` denies it outside the wrapper. **No hardcoded drifting IDs in tests** — use variables, generated values, or matchers, never a literal `PREFIX-N`.

## Hooks
- Hook configuration lives in your harness settings files (`.claude/settings.json`, `.codex/hooks.json`); both route through `yoke hook evaluate <event>`.
- Pre-tool guardrails, post-tool telemetry, session start, and session end are Python-owned. Never reintroduce shell scripts or per-policy shell choreography for hook execution.
- Emergency status repair is operator/debug only; route lifecycle repair through registered Yoke surfaces.

## Board
- `.yoke/BOARD.md` is auto-generated and untracked — never edit, stage, or commit it, and nothing rebuilds it automatically: run `yoke board rebuild` (`--print`, `--print-only`) for a current view.

## Health Checks
- **Every check declares what it applies to; the runner derives the rest** — `project_scope`, whether it reads the target tree, which runtimes, which capabilities. That derived set IS the per-project default; never branch on the literal project slug.
- **Passed, failed, and not-applicable are three different answers.** A check outside the applicable set reports `N/A` with its reason — never counted as a pass, never dropped.
- **Project-local checks live in the project,** under `.yoke/doctor/`, discovered pytest-style; a module that fails to import is a FAIL, not a skip. Depth: `verification.md`.

## Ouroboros
Observe → `ouroboros_entries` → `/yoke curate` → `/yoke doctor` → `/yoke simulate --system`.

## Lifecycle & Routing
- Canonical guide: `.yoke/docs/reference/lifecycle.md`. Each item pins immutable `workflow_id` / `workflow_version_id`; that definition owns stages, transitions, gates, policies, entry surfaces, skill bindings.
- **Never route by a remembered workflow name or copied progression.** Read `yoke workflows item get PREFIX-N`, then `yoke workflows version get WORKFLOW VERSION`; the binding whose half-open interval contains the live stage selects `/yoke <skill_id>`.
- A binding's `through_stage_id` is a fresh command and claim handoff. Worktree and task-graph shape come from `policies.worktrees` and `policies.generated_children`, never from a workflow-id branch.
- **Harness capability truth lives in the manifest,** `runtime/harness/<harness_id>/manifest.json` (contract: `runtime/harness/manifest-schema.md`). Read it before stating what a harness can do; never restate one of its facts in prose.

## Worktree Discipline
- **NEVER use `--no-worktree` unless the user explicitly asks. NEVER write implementation code on main.**
- **Authority over every lane is the work claim,** validated per call; launcher `cd` is convenience only. **Do not jump across a binding or invent a destination stage** — the active skill advances only inside its pinned half-open segment.
- **Every development-entry skill creates or reuses the item's registered worktree immediately** after the claim, read, and minimal survey — before deeper investigation or any edit.
- **Preparation starts from verified-current upstream.** A remote that cannot be read blocks as `upstream-unverified`; there is no offline fall back to the local branch. A diverged branch refuses as `upstream-stale`, its local commits preserved and never replayed or discarded. Nothing is ever reset, rebased, or force-updated.
- Depth: `lanes-and-claims.md`.

## Commit Discipline
- Commit after EVERY completed change — status and doc changes, not just code. No dirty working tree between tasks.
- **Never fabricate or expand a full commit hash from a short SHA.** Resolve it with `git -C <checkout> rev-parse HEAD` and verify with `git -C <checkout> cat-file -e '<sha>^{commit}'`.

## Session Continuity
- Leave the context your future self needs — decisions, dead ends, gotchas, the why — in the item's Progress Log, and distill hard-won research into docs before the session ends. Session continuity lives there and in field-notes.

## Documentation Discipline
- When a feature or rule changes, update ALL docs referencing it. Undocumented features are invisible.
- **Editing a file the install bundle packages — this one included — requires re-syncing the packaged snapshot in the same commit:** `yoke dev run -- python3 -m yoke_core.domain.install_bundle_tree_sync sync --target-root <checkout>`. The drift tests compare bytes, so an unsynced edit fails CI.

## Bug Discipline
- Capture bugs via `/yoke idea`; DO NOT FIX without knowing root cause. Minor observations go to a field-note.
- **Never route discovered work through harness task-suggestion surfaces** — they live outside the control plane: no claim, no lifecycle, no board row. File it via `/yoke idea`, `yoke dash`, or a field-note.

## Execution Discipline
- **Simulate before executing** — trace commands with real values. **Verify after executing** — never assume success, check the change landed. **Fear unintended effects** — do one, verify, then batch.

## Destructive Operation Discipline
- **Never run `git reset --hard`, `git checkout --`, `git checkout -f <branch>`, `git restore --worktree`, `git clean -f`/`-fd`/`-fdx`, `git stash drop`, `git stash clear`, or `rm` on files** unless confirmed Yoke-managed or user-authorized. These silently discard tracked-but-uncommitted changes, untracked files, or saved stashes — one incident had `git reset --hard` wipe a parallel agent's work in the same worktree. Commit or stash first, or use a non-destructive verb.
- **`git stash push`: `-m` MUST come BEFORE `--`** — everything after `--` is a pathspec, so a message flag there is silently consumed as a filename. Safe shape: `git stash push -u -m "reason" -- <paths>`.
- **User messages mid-sequence are checkpoints** — stop and answer first. Lint modes: `lanes-and-claims.md`.

## Deployment Rules
- Everything changed on remote MUST be edited locally first; ONLY copy local → remote.
- **A push is not release authority.** Merge the item, then let its hosted deployment flow own the exact commit, immutable artifacts, Stage proof, and any Production promotion. **Queue-declared projects land through the merge queue:** PR plus merge-when-ready, one `merge_group` gate proving the combined head, members recording batch receipts as covering evidence.

## Interaction Style
- **Prefer inline chat for summaries, checkpoints, and design iteration;** reserve structured chooser UIs for short binary or ternary decisions.
- **The work item is the plan.** When running a `/yoke` skill, the item's structured fields are the plan; never enter plan mode on your own, and if the plan is insufficient, stop and escalate.
<!-- END YOKE MANAGED BLOCK -->
