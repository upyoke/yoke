"""``core`` topic operational-primitives recipes for the agent packet.

Sibling of :mod:`schema_api_context_commands_core`. Holds the
operational primitives surfaced by live friction: how to read the current
session_id / actor_id, how to find the CLI adapter for a function id,
where to put a Python script that imports `runtime.*`, how to re-render
the agent files after editing a packet seed, and the 350-line
authored-file cap discovery recipe.

These are *operational* (how the agent reaches Yoke) rather than
*structural* (DB columns / function ids). Splitting them out keeps
:mod:`schema_api_context_commands_core` under the 350-line cap while
preserving the merged ``CORE_COMMANDS`` export the renderer consumes.

Recipe shape doctrine (current):
    The core function ids (`items.get.run`, `items.structured_field.replace`,
    `items.progress_log.append`, `lifecycle.transition.execute`,
    `lifecycle.repair_status.execute`,
    `events.query.run`, `claims.work.*`, `claims.path.{register,widen}`,
    `ouroboros.field_note.append`) use the strict ``yoke <subcommand>``
    grammar. Session-lifecycle CLIs, the `agents_render` renderer, the
    `yoke check file-line`, and `yoke db read`. Session-lifecycle CLIs,
    Atlas tooling, and the `db_router query` module form retain their
    multi-module shape as source-dev/operator-debug fallbacks.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


OPERATIONAL_COMMANDS: list[dict] = [
    {
        "topic": "core",
        "purpose": "Cancel / stop / fail a work item (terminal-exceptional)",
        "recipe": (
            "yoke claims work acquire --item PREFIX-N "
            "--reason 'superseded by PREFIX-X'\n"
            "yoke lifecycle transition PREFIX-N --to cancelled "
            "--reason 'superseded by PREFIX-X'\n"
            "yoke claims work release --item PREFIX-N "
            "--reason cancelled"
        ),
        "notes": (
            "Status writes require a claim. Substitute: cancelled "
            "(abandoned/superseded), stopped (paused), failed."
        ),
    },
    {
        "topic": "core",
        "purpose": (
            "Move a work item forward in lifecycle (claim → transition → release)"
        ),
        "recipe": (
            "yoke claims work acquire --item PREFIX-N --reason transition\n"
            "yoke lifecycle transition PREFIX-N --to refined-idea\n"
            "yoke claims work release --item PREFIX-N "
            "--reason transition-complete"
        ),
        "notes": (
            "Same shape for any non-terminal transition. Status "
            "vocabulary in .yoke/docs/reference/lifecycle.md. The function id "
            "`lifecycle.transition.execute` fires status gates, "
            "cascades, and GitHub sync."
        ),
    },
    {
        "topic": "core",
        "purpose": "Append to a work item's Progress Log (canonical agent shape)",
        "recipe": (
            "yoke claims work acquire --item PREFIX-N "
            "--reason progress-log-append\n"
            "yoke items progress-log append PREFIX-N "
            "--headline \"dispatched engineer\" --source orchestrator "
            "--content-file PATH\n"
            "yoke claims work release --item PREFIX-N "
            "--reason progress-log-append-complete"
        ),
        "notes": (
            "Write PATH with the entry body first. Dispatches "
            "items.progress_log.append, which read-merge-writes the "
            "Progress Log section atomically and stamps the timestamp."
        ),
    },
    {
        "topic": "core",
        "purpose": "Find or request the CLI adapter for a function id",
        "recipe": (
            "yoke <family> --help\n"
            "yoke ouroboros field-note append --kind new "
            "--evidence "
            "'Missing CLI adapter for items.foo.bar; agent surface "
            "boundary forbids HTTP/direct runtime import shapes'"
        ),
        "notes": (
            "`.yoke/docs/reference/db-reference/functions.md` lists the registered "
            "function ids per family, and the matching `yoke <subcommand> "
            "--help` carries that adapter's variants and flag matrix. The "
            "CLI grammar is reversible — dots become spaces, underscores "
            "become hyphens, a terminal `.run`/`.execute` drops — so a "
            "function id predicts its adapter name. "
            "**When you hit a recipe gap, fire `yoke ouroboros "
            "field-note append` immediately — before retrying, before "
            "moving on.** Run "
            "`yoke ouroboros field-note append --help` for the "
            "worked failure modes and decision tree. Do not start the "
            "function-call HTTP "
            "server or call the dispatcher from an ad-hoc Python "
            "one-liner to work around a missing adapter."
        ),
    },
    {
        "topic": "core",
        "purpose": "Operator-mode lifecycle repair after authoritative drift",
        "recipe": (
            "yoke lifecycle repair-status PREFIX-N --from CURRENT --to TARGET "
            "--reason 'operator-authored reconciliation' --dry-run"
        ),
        "notes": (
            "First run `yoke sessions touch --mode operator`; drop --dry-run "
            "to apply. `lifecycle.repair_status.execute` works over "
            "HTTPS/local, checks project permission and the pinned workflow, "
            "and limits its audited claim bypass to this request. Use "
            "`yoke claims work release --all-mine` to surrender claims "
            "without ending the session."
        ),
    },
    {
        "topic": "core",
        "purpose": "Branch / commit / CI inspection (read-only)",
        "recipe": (
            "git -C $(git rev-parse --show-toplevel) status --short --branch\n"
            "git -C $(git rev-parse --show-toplevel) log --oneline -20\n"
            "yoke github-actions check-ci "
            "$(yoke projects github-binding status --project yoke "
            "--field github_repo) "
            "ci.yml --branch main --project yoke\n"
            "git -C $(git rev-parse --show-toplevel)/.worktrees/PREFIX-N "
            "status --porcelain\n"
            "git -C $(git rev-parse --show-toplevel)/.worktrees/PREFIX-N "
            "rev-parse HEAD"
        ),
        "notes": (
            "Use -C with absolute path. Worktree paths under "
            ".worktrees/<branch>. The CI advisory dispatches "
            "github_actions.check_ci through gh_rest_transport; pass "
            "--head-sha for release authorization tied to one commit "
            "(bearer-token REST). Never expand a visible short SHA by "
            "guessing: resolve a reported or handed-off full commit hash with "
            "`git -C <checkout> rev-parse HEAD`, then verify it with "
            "`git -C <checkout> cat-file -e '<sha>^{commit}'`. For a GitHub "
            "REST verb that lacks a "
            "friendly helper, use `gh_rest_transport.RestRequest` with "
            "`request_with_retry`; do not guess a "
            "`github_actions_rest.rest_delete` helper."
        ),
    },
    {
        "topic": "core",
        "purpose": (
            "Field-note channel: log a failed/new/unclear recipe or observation"
        ),
        "recipe": (
            "yoke ouroboros field-note append --kind failed "
            "--evidence "
            "'R-CL-03 path-claim-narrow recipe used --remove; "
            "actual flag is --drop-paths'\n"
            "yoke ouroboros field-note append --kind new "
            "--evidence 'missing recipe: claim widen examples omit --item' "
            "--correlation-id polish-run-2026-05-20"
        ),
        "notes": (
            "**When you hit a recipe gap, fire `yoke ouroboros "
            "field-note append` immediately — before retrying, before "
            "moving on.** Kind: failed (recipe ran, wrong result), new "
            "(recipe missing), unclear (recipe present, unclear "
            "purpose). Run "
            "`yoke ouroboros field-note append --help` for the "
            "worked failure modes and decision tree. Surfaces in "
            "/yoke curate via OuroborosFieldNoteAppended events."
        ),
    },
    {
        "topic": "core",
        "purpose": "Current session_id / actor_id from a script",
        "recipe": (
            'echo "$YOKE_SESSION_ID" ; '
            'yoke db read '
            '"SELECT actor_id FROM harness_sessions WHERE session_id=\'$YOKE_SESSION_ID\'"'
        ),
        "notes": (
            "`$YOKE_SESSION_ID` is the fast path; when it is unset, "
            "ambient identity still resolves automatically (hook-written "
            "process-anchor registry, walked by every `yoke` CLI / "
            "dispatch call) — do NOT export session env vars to "
            "self-bootstrap, and treat `actor_session_missing` as an "
            "infrastructure bug to report. No `get_active_session_id` "
            "helper exists. The function-call surface resolves actor_id "
            "server-side from session_id — agents do not need to look it "
            "up themselves before dispatch. The actor_id SQL above is a "
            "diagnostic read, not a dispatch prerequisite; `db_router "
            "query` is only the source-dev/operator-debug fallback. "
            "`--session-id` flags are operator-debug overrides, recorded "
            "as `session_override`."
        ),
    },

    {
        "topic": "core",
        "purpose": "Where to put a project Python script",
        "recipe": "# put it under the project's tracked tools directory — never /tmp/*.py",
        "notes": (
            "Python's `sys.path[0]` for `python3 /tmp/foo.py` is /tmp, "
            "not cwd, so project imports may fail. Use a tracked project "
            "path or the project's environment runner. Prefer the canonical `yoke` CLI adapter "
            "(`yoke items structured-field replace --stdin`) for "
            "one-off structured-field writes."
        ),
    },
    {
        "topic": "core",
        "purpose": "Verify Python imports/tests against linked worktree source",
        "recipe": (
            "uv run --frozen python3 -m "
            "yoke_core.tools.module_source_path yoke_core\n"
            "uv run --frozen python3 -m yoke_core.tools.watch_pytest -- "
            "<project-test-path> -q"
        ),
        "notes": (
            "Fallback shape. `yoke watch pytest -- <paths>` already binds "
            "the worktree in a uv-managed checkout. Use the command from "
            "the linked worktree when the interpreter's editable install "
            "could still point at main, or when an externally-managed Python "
            "blocks `python3 -m pip install -e .`. Confirm the printed "
            "`yoke_core.__file__` path is under the worktree before "
            "trusting a green test run."
        ),
    },
    {
        "topic": "core",
        "purpose": "Re-render agent files after editing packet seeds",
        "recipe": (
            "uv run --frozen python3 -m yoke_core.domain.agents_render "
            "render --target-root <checkout>"
        ),
        "notes": (
            "After editing any `schema_api_context_*.py` seed file "
            "(`commands_core`, `tables_python_helpers`, etc.) or any "
            "canonical agent body, run the renderer or "
            "`test_byte_identity` fails. The renderer writes "
            "the installed Claude, Codex, and Cursor agent adapters from "
            "the seeds. Drift check: run `uv run --frozen python3 -m "
            "yoke_core.domain.agents_render check --target-root <checkout>`. "
            "Use the explicit `--target-root` form from "
            "linked worktrees; implicit cwd-based render targets are refused "
            "there."
        ),
    },
    {
        "topic": "core",
        "purpose": "authored-file line limit (file_line_check)",
        "recipe": "yoke check file-line --staged",
        "notes": (
            "Sanctioned local lint tool (not function-call backed). The "
            "default cap is 350 lines and a project overrides it with a "
            "`file_line_limit=N` key in `.yoke/project.config` "
            "(checked in, read off disk, so the offline hook agrees); "
            "comparison "
            "is `new <= limit` (so the limit itself is allowed). Rules: "
            "new files over the limit fail; existing under-cap files crossing "
            "upward fail; existing over-cap files growing further "
            "fail. When near the cap, prefer compressing the same "
            "file (collapse multi-line returns, drop one-line "
            "`__all__` lists, fold duplicate teaching) or split into "
            "a sibling module. `file_line_exception` entries are for "
            "intentionally unsplittable artifacts or non-authored data; "
            "do NOT add hard-rule files like AGENTS.md / CLAUDE.md. The pre-tool "
            "`hint_file_line_limit_approach` advisory warns on Write "
            "that would push a tracked authored file over the cap."
        ),
    },
]


__all__ = ["OPERATIONAL_COMMANDS"]
