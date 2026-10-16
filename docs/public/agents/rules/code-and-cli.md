# Code conventions and the agent CLI surface

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Code and teaching
<!-- /yoke:breadcrumbs -->

Deep home for the short rules in AGENTS.md. Read the applicable section before
its operation. Use the session packet for live schemas and
[function families](../../functions/index.md) for registered identities;
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
  is not retired.
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
A session holding a live steering seat on the repaired project, acting for an
org administrator, can run operator-approved row repair without a lane through
`yoke operator data-repair --content-file repair.json --reviewed-sha256 SHA --dry-run`.
Review the simulation audit before applying; [the repair contract](../../databases/operator-data-repair.md) owns its guards.
Never construct a DB path/DSN; lower-level queries are source-dev/operator-debug
only. SQL inequality is `<>`, never `!=`.

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

Follow the [teaching standard](../../documentation/index.md) and its
[navigation and validation contract](../../documentation/navigation.md) when
writing operation guidance.

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

## Related

- [Shell calls and CLI authority](shell-and-cli.md)
