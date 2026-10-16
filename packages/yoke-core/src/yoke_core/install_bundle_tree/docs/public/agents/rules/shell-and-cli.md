# Shell calls and CLI authority

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Shell and CLI
<!-- /yoke:breadcrumbs -->

Read this home before shell calls, registered CLI operations or serving-contract changes; it defines path authority, supported commands and compatibility floors.

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

## Canonical yoke CLI

Use `yoke <subcommand>` for wrapped operations. Dots become spaces, underscores
become hyphens, terminal `.run`/`.execute` drops; new function ids ship an adapter
before becoming agent-callable. HTTPS relays; non-prod local Postgres dispatches
in process as its product path; prod-flagged Postgres is operator-only.

Launcher installation/repair uses `yoke_core.tools.install_yoke_launcher` at
the registered source main checkout, never a linked lane. Install the released
CLI first with `curl -fsSL https://upyoke.com/install | sh`. The canonical
UV_TOOL_BIN_DIR/XDG_BIN_HOME or `~/.local/bin/yoke` shim runs that released
CLI; `YOKE_SOURCE_DEV=1` explicitly opts into YOKE_HOME source imports.
Claimed-lane checks use `yoke dev run -- <command>`. Repair/Doctor quick fix
quarantines PATH shadows, retaining them. Consult [install](../../start/install.md)
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

Human replies label values and preserve complete oversized results in a named
private evidence file. Entry instructions, handoffs and warnings stay immediate.
See [help and replies](../../reference/cli-help.md). Structured registered reads retain the
28,000-byte output limit. Oversized structured reads print no partial answer:
`read_output_limit_exceeded` names the narrower recipe and the explicit `--full`
opt-in. `--json` selects format; it does not bypass the limit. Lists serve
summary pages: QA plans require `--project P`, and QA/session lists default to
25 rows. Use `--limit N --offset N` for pages, or `--full` for complete rows
and the uncapped catalog. Steering JSON computes complete facts; add `--full`
to permit the full reply. Human steering pulls still show changed sections.

Routine summaries name withheld content and its deliberate command. Nothing is
silently dropped or condensed by size. Messages lists name body get; QA plan get
names `--full` for probe instructions/config/expected outcome and proof tail/
evidence/review. Execution-instruction resolve defaults to Before-creation ids/
headings; use `--full` to read rules before attesting at filing. Delivery-point/
stage-bucket choose read/entry delivery; see [instruction contract](../../reference/execution-instructions.md).

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

## Related

- [Code conventions and the agent CLI surface](code-and-cli.md)
