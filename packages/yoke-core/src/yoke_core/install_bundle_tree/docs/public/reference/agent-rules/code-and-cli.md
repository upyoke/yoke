# Code conventions and the agent CLI surface

Deep home for the short rules in AGENTS.md. Read the applicable section before
its operation. Use the session packet for live schemas and
[function families](../db-reference/functions.md) for registered identities;
teaching prose helps discovery, while registered results establish live state.

## Code conventions

- Commit every completed change. Never fabricate or expand a full commit hash:
  resolve with `git -C <checkout> rev-parse HEAD`, then verify with
  `git -C <checkout> cat-file -e '<sha>^{commit}'`.
- Describe failed commands systemically: missing dispatch context, stale
  references, truncated context or a teaching gap. Never attribute failure to
  "agent error/mistake" in items, commits, reflections or reports. Name the
  system change needed; this does not excuse an ungrounded judgment.
- Yoke-owned operations are registered functions first. Name their function id
  in new teaching and use the canonical `yoke` adapter. Git, gh and external
  tooling remain command-shaped.
- Use Python entrypoints/packaged commands for stateful launchers, hooks,
  helpers, installers and runners; no tracked `.sh` choreography. CLIs resolve
  session identity. Pass content through `--stdin`/`--content-file`; shell remains
  suitable for tests, discovery, git inspection and diff/screenshot captures.
- One repeated value has one owner: machine-local tunables in
  `~/.yoke/config.json`, project/environment authority in DB capability settings,
  or one Python constant. Capability contract changes converge stored documents
  in the same change, including required/retired keys and narrowed enums.
- Migration modules are permanent ordered history. Each universe's pending set
  is history minus its applied ledger. Baseline squash requires every known
  install past the entries, evidenced by fleet-wide `HC-pending-migrations`;
  it never authorizes deleting modules. Read [DB rules](databases.md).
- `item_id` is bare integer `items.id`; a public ref's numeric tail is
  `items.project_sequence`. Resolve the project-scoped ref before storing or
  asserting the id. Resolve GitHub issue numbers through `github_issue`.
- Purge retired columns/tables/modules/commands/helpers/files from tracked
  content in the retirement commit. An actively supported compatibility alias
  is not retired. `HC-obsoleted-terms` enforces this.
- Public refs in live code/docs describe active state only. Historical
  provenance belongs in commits; durable architectural reasons belong under
  `docs/archive/decisions/` with a topic name. `HC-historical-yok-n-cruft`
  enforces that boundary.

## Name for a repository reader

Assume future readers have no planning artifacts. Name FILES and DIRECTORIES,
symbols, tests, sections, commands, events, settings and comments for current
function, purpose, mechanics, behavior or domain role. Planning artifacts are
scaffolding; the live codebase is the building.

No work-item/epic, strategy/plan/initiative/milestone, phase/stage/tier/slice/
track/wave/batch, task/thread, criterion/requirement/spec-section, field-note,
version/rollout, branch/worktree provenance in live names or explanations.
Artifact identifiers are permitted only when themselves runtime/domain data.
Ask: would this explain itself to a maintainer who sees only the repository?
Translate a numbered criterion guard to `submission_receipt_guard`, a retry
work-item shim to `transient_retry_shim`, and a numbered adapter directory to
`install_adapters/`. Name tests for behavior, not the item that commissioned them.

This targets provenance of code, preserving emitted/parsed runtime data,
acceptance-checkbox labels, enums, keys, DB columns, errors, events and synthetic
test fixtures. `HC-acceptance-criterion-provenance` is FAIL posture; its data
exceptions cover checkbox-format producers/teachers/tests, archives and derived
rendered adapters of exempt canonical bodies. Harness exemptions derive from
`RENDERED_AGENT_DIRS`, rather than hand-maintained lists.

## Verify before asserting

Directly check a named column/function/path/flag/table/module before asserting
it exists. A noun phrase from a spec or commit does not establish an identifier.
Use scoped `rg`, a file read, a packet or diagnostic `yoke db read` as applicable.
Apply this to code, chat, comments and PR descriptions.

For capability, item/session/claim/launch/deployment state or refusal reasons,
use the authoritative registered result/projection/refusal/help and name the
evidence beside the conclusion. A code read or teaching paragraph cannot prove
what the serving control plane currently supports. Verify the caller's own
surface and composed launch preview rather than blaming staffed items or
manually joining capability sources. Distinguish capacity counters by their
declared counted population; completion alone proves no counter changed.
Use manifest/live wake projections and probes for harness capability claims.
Correct inaccurate teaching when discovered.

## DB authority and structured content

The DB is authoritative; `.yoke/BOARD.md` and `.yoke/strategy/` are generated
views. Read item bodies on demand. Backlog access uses registered `items`,
`lifecycle` and structured-field adapters; see [item writes](item-writes.md).
Author a file or stdin content directly for `items.structured_field.replace`;
do not read a field into a variable and pipe it back as a mutation.

Strategy corpus equals the project's `strategy_docs` rows. Cold starts seed
MISSION, VISION, MASTER-PLAN and LANDSCAPE; projects may add focused plan slugs.
Use the registered list/get/render/ingest/create/archive commands and their help:

```text
yoke strategy doc list --project P
yoke strategy doc get SLUG --project P
yoke strategy render --target-root CHECKOUT --project P
yoke strategy ingest SLUG --target-root CHECKOUT --project P --dry-run
```

Render defaults to active docs, omits unchanged bodies and returns metadata for
known-active docs now archived. `--include-archives` or an explicit slug fetches
archive bodies. Review dry-run before real ingest. Create requires single-line
Summary and free-text State; help owns shared limits. Edits/ingest/restore retain
unique valid Summary/State sections and normalized headings; restore permits
overrides for legacy content. Archive moves the view to `.yoke/strategy/archive/`
and retains the row. Edit generated views only through documented ingest paths.

Raw SQL is diagnostic escape-hatch authority: `yoke db read "SELECT ..."`.
Never construct a DB path/DSN; lower-level queries are source-dev/operator-debug
only. SQL inequality is `<>`, never `!=`.

## Shell calls and path authority

Each call has fresh variables/exports. Claude may retain cwd within declared
roots; parallel calls share that cwd. Use absolute paths, `git -C ABSOLUTE_PATH`
and an explicit declared workdir/leading `cd` for relative or computed writes.
The client stamps workdir from the manifest's `identity.command_workdir_source`.

Active work claims authorize claimed lanes, main control-plane paths excluding
worktrees, and free paths `/tmp` or `/var/folders/...`. Launcher cwd grants no
authority. Read-shaped calls may additionally name operator-home reference
documents; dot-prefixed home components remain on curated installed-read rules.
Direct main source writes while holding a live lane refuse; registered adapters
and ignored generated renders are distinct from direct source writes. Missing/
stranded lane is advisory; `2>&1` names no file and is not a write target.
`# lint:no-worktree-path-check` is audit-only; deliberate main-write exceptions
use the documented `# lint:allow-lane-main-write` authority. Read
[lane rules](lanes-and-claims.md) before resolving an overlap or exception.

Another item's live lane allows reads and refuses writes (`foreign_lane`).
Use one plain read-verb `git -C LANE ...`: status/diff/log/show/ls-files/ls-tree/
rev-parse/blame/describe/shortlog, or listing-only branch/remote/config without
positional arguments. `cat`, `ls` and native Read also work. No redirect, chain,
`--output`, write or state-changing verb. Inspect a neighbor's shared-file diff
with a plain `git -C LANE diff -- PATH`.

### zsh and input hazards

- Capture command output before piping; brace `${name}:` to avoid zsh modifiers.
  Single-quote literal search patterns; backticks inside double quotes execute.
- Free text containing backticks or `$(` in a double-quoted Yoke argument is
  refused. Use stdin/content-file from quoted heredoc, or capture a computed
  value first and pass its variable. Put `rg` options before pattern and paths.
- Enumerate optional globs with `rg --files`, or quote tool-consumed patterns.
  Quote URLs containing `?`. Use `python3`; never reuse zsh `path`/`status` vars.
  `mktemp` templates end in `XXXXXX`.
- Anchor discovery in the checkout or named harness dotdir. Binary discovery
  reuses `resolve_native_cli`/`_CLI_FALLBACKS`; home-wide scans receive its advisory.
  User-selected documents follow user authority and OS privacy prompts. The
  system privacy database remains refused because it exposes every app's grants.

## Intake and operation teaching

Item/task titles obey the target project's effective `title_max_length`:
integer minimum 10/default 100, dashboard Project settings and registered workflow
definition read. Create and explicit edits enforce the resolved project limit;
lowering it does not retroactively flag existing titles. `HC-title-length`
checks invalid stored limit settings; title columns remain unbounded text.

Each create names a workflow and allowed typed entry surface: web_form, cli,
harness_skill or promotion. Idea uses registered items.create/harness_skill;
forms and operator commands use their own surfaces. Dry-run/test-isolated
targets may omit it. Architect decomposes `generated_children=epic_tasks` into
epic_tasks; do not pre-file imagined child backlog items.

Teach one short recipe plus one actionable sentence everywhere an operation
appears; its help owns variants, examples, flags and decisions. Denials teach
their own reason/recovery, not repeated standing policy. Git/gh harness-executed
families and watcher wrappers have no Yoke help, so carry their full recipes.
Anti-pattern teaching belongs in denials. Enforcement of this teaching is deferred.

## Canonical yoke CLI

Use `yoke <subcommand>` for wrapped operations. Dots become spaces, underscores
become hyphens, terminal `.run`/`.execute` drops; new function ids ship an adapter
before becoming agent-callable. HTTPS relays; non-prod local Postgres dispatches
in process as its product path; prod-flagged Postgres is operator-only.

Launcher installation/repair uses `yoke_core.tools.install_yoke_launcher` at
the registered editable main checkout, never a linked lane. It writes the
canonical XDG_BIN_HOME or `~/.local/bin/yoke` shim. Repair/Doctor quick fix
quarantines PATH shadows, retaining them. Consult [install](../../install.md)
and launcher help before repair.
DB-router/service-client forms are operator-debug only. HTTP function-call
server/curl-localhost/YOKE_API/direct runtime-API imports are not agent surfaces.
The runtime-import and curl lints use project `.yoke/lint-config`, default deny:
`lint-no-agent-runtime-api-import-from-c` and `lint-no-agent-curl-against-yoke-api`
(matching underscore-form guard keys).

Refusals have separate truthful reason and reachable recovery; use
`yoke_core.domain.refusal_recovery.compose_refusal`. Report every evaluated
partial-state fact. Verify recovery is reachable or state its condition; if none
is reachable, name the escalation owner. Mark stamps/capture flags as bookkeeping,
never health. Surfaces answering the same question cross-reference or defer.

Ask narrower questions rather than trimming answers. Adapter stderr remains
visible on mutations; stdout remains whole (`lint-yoke-adapter-stderr-visibility`,
guard `lint_yoke_adapter_stderr_visibility`, default deny; help out of scope).
Capture long commands once and read the capture after exit.

<!-- BEGIN GENERATED: read-recipe -->
Want part of an answer? Ask the narrow question — every read has a shape that serves it.

| What you want | The shape that serves it |
| --- | --- |
| The routine answer | `yoke <command> <arguments>` — Every registered read is already scoped to its routine answer, and one that holds something back names what it withheld and the command that serves it. |
| One field of a record | `yoke items get PREFIX-N status` — A read that accepts field names serves exactly those fields; add --section "## Heading" to serve one block of a long text field. |
| One value inside stored settings | `yoke projects environment-settings get --project P --environment E --path key.path` — A projection read takes the path to the value and serves that value. |
| Specific rows | `yoke db read "SELECT id, status FROM items ORDER BY id DESC LIMIT 20"` — The columns, the filter, and the row count are all part of the question; --format lines serves pipe-delimited rows. |
| An ordinary pending message | `yoke messages list --state pending` — The list serves one row per message; `yoke messages get MESSAGE-ID` then serves that one message. Injected launch messages are absent from this list. |
| A launched session's assigned message | `yoke session-control launch get LAUNCH-ID --json` — Read its message_id, then `yoke messages get MESSAGE-ID` and `yoke messages acknowledge MESSAGE-ID`. An unacknowledged launch remains in flight and expires with a named diagnostic. |
| A long run's full output | `tail -80 <raw-capture>` — A watcher wrapper prints its raw capture path, so read that file once the run exits; a command with no wrapper is captured first with `_tmp=$(mktemp /tmp/yoke-cmd.XXXXXX); <command> >"$_tmp" 2>&1; _rc=$?` and the file read. |
| Everything a summary named as held back | `yoke <command> <arguments> --full` — The summary names this flag whenever it has more to serve, so the deliberate read is always one flag away from the routine one. |
| The response envelope's structure | `yoke <command> <arguments> --json` — --json chooses the shape of the answer and pairs with every narrowing above. |
<!-- END GENERATED: read-recipe -->

### Routine versus deliberate reads

Routine summaries name withheld content and its deliberate command. Nothing is
silently dropped or condensed by size. Messages lists name body get; QA plan get
names `--full` for probe instructions/config/expected outcome and proof tail/
evidence/review. Execution-instruction resolve defaults to Before-creation ids/
headings; use `--full` to read rules before attesting at filing. Delivery-point/
stage-bucket choose read/entry delivery; see [instruction contract](../execution-instructions.md).

Full item reads carry On-every-read and live-entry instructions once. Narrow
field/section/Progress Log reads name the full read. Work-claim receipts and
composed worker mandates deliver full instructions statelessly; successful
transitions return entered-bucket instructions. Message and QA detail/editor UIs
request detail=full when displaying withheld content.

Operation status: wrapped has an adapter; permanent stays multi-module
(coordination claims, internal path claims, watchers); pending is future.
`HC-fallback-registry-coherence` verifies the registry.

## Serving floors

Migration MINIMUM_SERVING_VERSION covers schema only. New function ids declare
registry `minimum_serving_version` (`next-release` until release); the registry
refuses newly advertised ids without a floor. An older engine returns
function_version_skew with the required floor. Recovery names a served older
command or the control-plane operator, avoiding a deployment circular dependency.

New response fields either degrade to declared previous behavior (Fleet body
when digest is absent) or refuse with a named floor. Required identity/acceptance
receipts cannot invent defaults or silently use an older concurrent attempt.
Absence is compatibility evidence, not permission to raise an unexplained error.

## Simplify

Idea, Refine, Implement, Conduct, Shepherd and Polish apply reuse, quality and
efficiency plus future-concept pull-forward. Use discovered end-state primitives
(actors/sessions/leases/claims/approvals/overrides/evidence/runs/journals/packets/
resource locks/shared coordination) rather than temporary alternatives.

- Reuse: name an existing file/helper/template/skill/event/command/config before
  adding one, or state "no relevant existing surface" with the search evidence.
- Quality: smallest complete spec/plan/diff and explicit exclusions when scope
  invites creep. Remove redundant state, parameter sprawl, varied copies, leaky/
  stringly abstractions, nested wrappers and WHAT comments; preserve WHY.
- Efficiency: cheapest useful path; remove repeated reads/API/computation, N+1,
  missed concurrency, hot-path/no-op bloat, prechecks, unbounded state and cleanup
  gaps. New tables/events/skills/settings/commands justify extension versus creation.

Idea pre-check is advisory presence; one-line no concerns is valid. Refine uses
feedforward scope/reuse/new-surface/end-state-or-absorption lenses. Authoring uses
them on code and the smallest complete diff. Polish runs one sequential pass of
the worktree diff before staleness/tests: fix inline, skip false positives,
continue with no changes; deliverable is a commit. This cross-harness v0 adds no
lifecycle phase, storage fields, dedicated agent, parallel axis fan-out or
whole-repository cleanup mandate.

## Shell path-use analysis

Reuse `lint_shell_path_use.analyze_shell_path_use` and
`lint_payload_path_use.extract_payload_path_uses` with their splitter, resolver,
write and remote-resource rules. Keep operand roles: a path alone establishes
neither content nor capacity nor mutation authority. Supported capacity shape
is `df -k PATH [PATH ...]`; other/unknown syntax retains normal restrictive
analysis. No second parser or broad metadata/read exception.

Compare full original calls under isolated historical authority when changing
classification. Separate guard result from process exit; missing historical
context is inconclusive. Unresolved homes refuse
unresolved_executing_machine_home: restore canonical client-home metadata or
use an absolute executing-machine path, never a held-lane-relative substitute.
Capacity operands requiring glob expansion retain ordinary authority.
