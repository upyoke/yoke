"""``core`` topic watcher / Monitor recipes for the agent packet.

Sibling of :mod:`schema_api_context_commands_core` and
:mod:`schema_api_context_commands_core_operational`. Holds the
watcher / background-command recipes that have no current packet home:
high-friction patterns for ``watch_pytest`` / ``watch_doctor`` /
``watch_merge`` / ``watch_deploy`` plus the foreground variant used by
Yoke subagents.

Recipe shape doctrine (current):
    The watcher wrappers (``yoke_core.tools.watch_pytest``,
    ``watch_doctor``, ``watch_merge``) are deliberately
    **tool-shaped surfaces, not function-call dispatched**. Per
    CLI grammar contract, families whose disposition is
    ``agent_executes_via_harness`` are explicitly NOT in the
    ``yoke`` CLI — agents reach them via native harness Bash.
    These watcher recipes therefore retain the watcher module form by design; they
    are not awaiting a ``yoke`` CLI adapter. The same applies to
    ``tail`` / ``grep`` / ``git -C`` shapes inside watcher recipes.

The recipes here are also deliberately harness-neutral: the watcher
wrappers print harness-specific instructions themselves via
``--print-streaming-pair`` when running under a harness with a
streaming surface, and run foreground directly under Codex's native
PTY stream. Recipe text therefore avoids naming any Claude-only
primitive (the conditional-block renderer enforces this for any seed
that lands in both ``main_agent`` and cross-harness packets).

Splitting these into a dedicated topic-sibling keeps the parent
:mod:`schema_api_context_commands_core` under the 350-line authored-file
cap while preserving the merged ``WRAPPER_COMMANDS`` export the renderer
consumes via :mod:`schema_api_context_commands`.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


WATCHERS_COMMANDS: list[dict] = [
    {
        "topic": "core",
        "purpose": "Run pytest with background watcher (main session)",
        "recipe": (
            "uv run --frozen python3 -m yoke_core.tools.watch_pytest -- "
            "runtime/api/ runtime/harness/ tests/\n"
            "# Canonical full Yoke gate. For a harness background stream:\n"
            "uv run --frozen python3 -m yoke_core.tools.watch_pytest "
            "--print-streaming-pair -- runtime/api/ runtime/harness/ tests/\n"
            "# Paste the printed pair into the harness's "
            "background + progress-tail surfaces.\n"
            "# After completion: tail -80 <raw-capture> "
            "(the helper-resolved path the wrapper printed)"
        ),
        "notes": (
            "This exact three-suite target is the canonical full Yoke gate; "
            "it injects xdist `-n auto`. Pass --no-parallel after `--` "
            "for sequential order-sensitive debugging. The wrapper mints "
            "the raw + progress capture pair via "
            "yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair "
            "under the machine temp root's watcher-captures directory and prints the resolved "
            "paths; --raw-capture <path> is the operator carve-out for "
            "pinning to a known location. Subagents must run the foreground "
            "variant below — backgrounded watchers from subagent context "
            "are denied by lint-subagent-background. `uv run --frozen` "
            "materializes the locked dev environment in a clean worktree, "
            "so the wrapper and application dependencies are importable "
            "without ambient PYTHONPATH or virtualenv activation."
        ),
    },
    {
        "topic": "core",
        "purpose": "Run pytest foreground inside one tool call (subagent)",
        "recipe": (
            "uv run --frozen python3 -m yoke_core.tools.watch_pytest -- "
            "runtime/api/test_my_module.py -q\n"
            "# Blocks within the same tool call; the wrapper mints raw + "
            "progress captures via project_scratch_dir.watcher_capture_path "
            "under the machine temp root's watcher-captures directory and prints them; "
            "tail -80 <raw-capture> on failure."
        ),
        "notes": (
            "Subagent tool-call turns are atomic — backgrounded watcher "
            "patterns strand processes. Enforced by "
            "lint-subagent-background."
        ),
    },
    {
        "topic": "core",
        "purpose": "Run doctor with background watcher (main session)",
        "recipe": (
            "uv run --frozen python3 -m yoke_core.tools.watch_doctor "
            "--print-streaming-pair -- --quick\n"
            "# Paste the printed pair into the harness's "
            "background + progress-tail surfaces."
        ),
        "notes": (
            "Doctor must run under this wrapper — bare invocations risk "
            "the inverted-redirection trap (`2>&1 > file` silently drops "
            "stderr). The wrapper writes raw + filtered captures and "
            "auto-exits on its sentinel."
        ),
    },
    {
        "topic": "core",
        "purpose": ("Run done_transition / merge_worktree with watcher (main session)"),
        "recipe": (
            "uv run --frozen python3 -m yoke_core.tools.watch_merge "
            "--print-streaming-pair merge-worktree -- YOK-N\n"
            "# Subcommands: done-transition <args>, merge-worktree <args>"
        ),
        "notes": (
            "watch_merge owns the merge filter regex (section banners, "
            "step headers, errors, warnings, RESULT_FILE=). Use for any "
            "merge or done_transition; never hand-author the filter."
        ),
    },
    {
        "topic": "core",
        "purpose": (
            "Run item-less deployment pipeline with pinned product source "
            "(admin/source-dev)"
        ),
        "recipe": (
            "source_checkout=<source-checkout>; target_branch=<main-or-stage>; "
            'git -C "$source_checkout" fetch origin "$target_branch" && '
            'git -C "$source_checkout" checkout --detach FETCH_HEAD && '
            'PYTHONPATH="$source_checkout/packages/yoke-contracts/src:'
            "$source_checkout/packages/yoke-cli/src:"
            "$source_checkout/packages/yoke-core/src:"
            "$source_checkout/packages/yoke-harness/src:"
            '$source_checkout${PYTHONPATH:+:$PYTHONPATH}" '
            "YOKE_ENV=<control-plane-env>-db-admin "
            "YOKE_GITHUB_ACTIONS_RELAY_ENV=<hosted-control-plane-env> "
            "python3 -m "
            'yoke_core.tools.watch_deploy --product-src "$source_checkout" '
            "-- {run-id}"
        ),
        "notes": (
            "watch_deploy supplies the `python3 -m "
            "yoke_core.domain.deploy_pipeline` prefix itself. `--product-src` "
            "is a watcher option and must precede `--`; pass only bare "
            "deploy_pipeline args after `--` (`run-...`, optional "
            "`--from-stage`, and other pipeline options). The product "
            "checkout pins the executing code, build context, and product "
            "release SHA; use the same checkout on every retry or resume. "
            "The watcher validates its exact HEAD and injects the canonical "
            "12-character registry tag. A legacy explicit `--image-tag` is "
            "accepted only when it resolves to the same HEAD and is "
            "canonicalized before dispatch. Fetching alone does not move "
            "the checkout; detach it at `FETCH_HEAD`. The explicit "
            "worktree-source `PYTHONPATH` prevents an installed older Yoke "
            "from running the outer watcher. Claude adds "
            "`--print-streaming-pair` immediately "
            "before `--`; Codex/native shells run the shown command. This "
            "local-Postgres control-plane recipe is for "
            "source-dev/admin or audited break-glass operation only; "
            "routine access stays on `/yoke usher`, domain-specific "
            "`yoke ...` wrappers, or `yoke db read` over the selected "
            "HTTPS/API authority. Do not use `YOKE_ENV=<env>-db-admin` as a "
            "normal retry after a product read fails. Item-less environment "
            "deploys are valid only as operator-attended admin runs: create "
            "the run with `db_router runs create-run` under the project that "
            "owns the deployment environment and flow (which may differ from "
            "the product project), resolve the target branch SHA from the "
            "explicit product checkout, then execute the printed run id "
            "through this watcher with `--product-src` and `--image-tag`."
            " Normal attended deploys select the hosted GitHub Actions relay. "
            "Only the first control-plane bootstrap that introduces or repairs "
            "that relay may replace `YOKE_GITHUB_ACTIONS_RELAY_ENV=...` with "
            "`YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY=1`; never leave authority "
            "selection implicit."
        ),
    },
    {
        "topic": "core",
        "purpose": (
            "Run pytest with explicit raw-capture path (post-completion inspection)"
        ),
        "recipe": (
            "uv run --frozen python3 -m yoke_core.tools.watch_pytest "
            "--raw-capture <PATH> -- "
            "runtime/api/test_my_module.py -q\n"
            "tail -80 <PATH>"
        ),
        "notes": (
            "--print-streaming-pair mints the capture path automatically "
            "via project_scratch_dir.mint_watcher_capture_pair "
            "(machine temp root watcher-captures/...); the explicit "
            "--raw-capture <PATH> form is the operator carve-out for "
            "callers that want a known path (CI scripts collecting "
            "artifacts). Prefer the helper-resolved default."
        ),
    },
    {
        "topic": "core",
        "purpose": "Run doctor focused on specific HC rules",
        "recipe": (
            "uv run --frozen python3 -m yoke_core.tools.watch_doctor -- --quick\n"
            "uv run --frozen python3 -m yoke_core.tools.watch_doctor -- "
            "--only HC-event-registry-coverage,"
            "HC-event-callsite-registry-sync\n"
            "uv run --frozen python3 -m yoke_core.tools.watch_doctor -- --full --json"
        ),
        "notes": (
            "--quick = fast subset; --only takes a comma-separated list "
            "of HC slug ids for targeted reruns; --json for machine "
            "output. Doctor CLI surface, not a wrapper-only flag."
        ),
    },
]


__all__ = ["WATCHERS_COMMANDS"]
