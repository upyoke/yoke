"""``core`` topic watcher / Monitor recipes for the agent packet.

Sibling of :mod:`schema_api_context_commands_core` and
:mod:`schema_api_context_commands_core_operational`. Holds the
watcher / background-command recipes that have no current packet home:
high-friction patterns for ``watch_pytest`` / ``watch_doctor`` /
``watch_merge`` plus the foreground variant used by
Yoke subagents.

Recipe shape doctrine (current):
    The watchers are invoked as ``yoke watch <kind>`` commands. They
    remain **tool-shaped surfaces, not function-call dispatched** — the
    adapter runs a local subprocess and carries no function id — but the
    console script is what makes them resolvable everywhere, so it is the
    taught form. The module invocation
    (``python3 -m yoke_core.tools.watch_pytest``) stays callable as the
    operator-debug fallback. ``tail`` / ``grep`` / ``git -C`` shapes
    inside watcher recipes stay command-shaped by design.

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
            "yoke watch pytest "
            "--impacted main\n"
            "# Default local check. Full three-anchor sweep (CI's job; "
            "local CI-outage fallback):\n"
            "yoke watch pytest "
            "--print-streaming-pair -- runtime/api/ runtime/harness/ tests/\n"
            "# Paste the printed pair into the harness's "
            "background + progress-tail surfaces.\n"
            "# After completion: tail -80 <raw-capture> "
            "(the helper-resolved path the wrapper printed)"
        ),
        "notes": (
            "The impacted selection is the local default; the three-suite "
            "target is the full Yoke gate CI runs on every pull request "
            "and push to main, and locally it is the CI-outage fallback. "
            "Both inject xdist `-n auto`. Pass `-n 0` after `--` "
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
            "yoke watch pytest -- "
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
            "yoke watch doctor "
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
            "yoke watch merge "
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
            "Run pytest with explicit raw-capture path (post-completion inspection)"
        ),
        "recipe": (
            "yoke watch pytest "
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
            "yoke watch doctor -- --quick\n"
            "yoke watch doctor -- "
            "--only HC-event-registry-coverage,"
            "HC-event-callsite-registry-sync\n"
            "yoke watch doctor -- --full --json"
        ),
        "notes": (
            "--quick = fast subset; --only takes a comma-separated list "
            "of HC slug ids for targeted reruns; --json for machine "
            "output. Doctor CLI surface, not a wrapper-only flag."
        ),
    },
]


__all__ = ["WATCHERS_COMMANDS"]
