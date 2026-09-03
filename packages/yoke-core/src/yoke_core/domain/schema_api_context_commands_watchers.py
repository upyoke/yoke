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
            "--impacted main --bounded\n"
            "# Default change-scoped check (--bounded is a no-op). Runs on "
            "the project's CI when it declares ci_workflow_file; --local "
            "runs it on this machine. Full sweep "
            "(CI's job; local --widen / CI-outage fallback) — pass your "
            "project's test anchors:\n"
            "yoke watch pytest "
            "--print-streaming-pair -- <project test anchors>\n"
            "# Paste both printed lines verbatim into the harness's "
            "background + progress-tail surfaces — the printed "
            "--raw-capture/--progress-capture flags are what bind the run "
            "to the tail.\n"
            "# After completion: tail -80 <raw-capture> "
            "(the helper-resolved path the wrapper printed)"
        ),
        "notes": (
            "The impacted selection is the default change-scoped check and "
            "needs no project-specific paths. For a project declaring a "
            "ci_workflow_file capability it executes on that CI, not on "
            "this machine: the wrapper pushes the lane commit, dispatches "
            "the selection workflow against it with the merge base, "
            "streams the run, and adopts its conclusion (0 success, 1 "
            "failure, 2 refused before dispatch, 3 timed out, 4 CI "
            "unreachable or dispatch refused, 5 cancelled). Commit first: "
            "a remote run refuses an uncommitted tree and a checkout on "
            "the base branch, and drops -n/--numprocesses/--rootdir, which "
            "describe this machine. Pass --local (or set "
            "YOKE_PYTEST_LOCAL=1 for a whole shell) to run it here "
            "instead; local runs take their xdist workers from one "
            "machine-wide budget that waits and names the holder when "
            "nothing is free. The full sweep is CI's job on every "
            "pull request and push to main, and locally it is the "
            "CI-outage fallback; its anchor paths are per-project — read "
            "them from your project's registered verification command "
            "(its QA plan) or your project rules file, and never carry "
            "another project's anchors over. "
            "Both inject xdist `-n auto`. Pass `-n 0` after `--` "
            "for sequential order-sensitive debugging. The wrapper mints "
            "the raw + progress capture pair via "
            "yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair "
            "under the machine temp root's watcher-captures directory and prints the resolved "
            "paths; --raw-capture <path> is the operator carve-out for "
            "pinning to a known location. Running the wrapper without the "
            "printed capture flags mints a different pair, so the tail "
            "follows a file the run never writes and refuses once its "
            "grace window passes. Subagents must run the foreground "
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
            "<project-test-path>/test_my_module.py -q\n"
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
            "# Paste both printed lines verbatim — the printed "
            "--raw-capture/--progress-capture flags bind the run to the tail."
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
        "purpose": ("Run merge or done-transition with watcher (main session)"),
        "recipe": (
            "yoke watch merge "
            "--print-streaming-pair merge-worktree -- PREFIX-N\n"
            "# merge-item enqueues and exits; a launched worker adds --wait"
        ),
        "notes": (
            "watch_merge owns the merge filter regex (section banners, "
            "step headers, errors, warnings, RESULT_FILE=). Use for any "
            "merge or done_transition; never hand-author the filter. "
            "merge-item --wait holds the landing inline: an operator-opened "
            "session takes the enqueue/re-enter handoff, while a launched "
            "headless worker passes --wait through this wrapper and holds "
            "its turn, because it cannot be prompted on the "
            "landing-complete message. Never block a bare foreground call "
            "on the full wait."
        ),
    },
    {
        "topic": "core",
        "purpose": "Wait on a commit's CI runs with watcher (main session)",
        "recipe": (
            "yoke watch ci-run\nyoke watch ci-run -- <branch-or-sha> --workflow <name>"
        ),
        "notes": (
            "Owns the CI filter; never hand-author one. Resolves the ref with "
            "`git rev-parse <ref>^{commit}`, matches that exact head SHA, and "
            "matches --workflow against the workflow name, not the run title."
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
            "<project-test-path>/test_my_module.py -q\n"
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
