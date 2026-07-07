"""Universal hook ordering → per-harness hook config rendering.

Translates the universal :mod:`yoke_contracts.hook_runner.hook_ordering`
chains into native hook config shapes:

- Claude ``settings.json`` ``hooks`` block (matcher + nested ``hooks`` list).
- Codex ``hooks.json`` ``hooks`` block (matcher + ``hooks`` list).

Both harnesses now collapse to one CLI command per ``(event, matcher)``
pair. The command (``yoke hook evaluate <event>``) is the stable project
hook boundary; the CLI currently delegates to the local hook runner, and can
later choose local runtime or cloud transport without changing project hook
configs. The rendered manifest no longer enumerates per-lint module command
lines.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.hook_ordering import (
    HOOK_ORDERING,
    matchers_for,
    ordered_pipeline_for,
)


# ---------------------------------------------------------------------------
# Claude settings.json — runner-per-event rendering
# ---------------------------------------------------------------------------

# Every Claude hook entry routes through ``yoke hook evaluate``. The CLI
# takes the event name as a positional arg and reads the chain from
# :mod:`yoke_contracts.hook_runner.hook_ordering` through today's local
# runner. The matcher fans out at the manifest level, but the per-matcher
# dispatch happens behind the CLI via the loaded ``AdapterCapability``.

_YOKE_HOOK_EVALUATE = "yoke hook evaluate"


def _claude_command(event: str) -> str:
    # Wrap in a zsh login shell so the operator's ``~/.zprofile`` (or system
    # equivalent) loads the brew shellenv before ``yoke`` runs. macOS GUI
    # apps like Claude.app are launched with the minimal launchd PATH that
    # omits ``/opt/homebrew/bin``, so an unwrapped CLI can miss the operator's
    # installed entrypoint before any Yoke code runs. ``-l`` is required to
    # source ``~/.zprofile``; ``-c`` keeps the shell non-interactive so it exits
    # after the command. Stdin is forwarded through the shell to the CLI
    # child, so Claude's hook event JSON payload still reaches the runner.
    return f"/bin/zsh -lc '{_YOKE_HOOK_EVALUATE} {event}'"


def _claude_hook_entry(event: str) -> dict:
    return {"command": _claude_command(event), "type": "command"}


def _claude_chain_for(event: str, matcher: str) -> list[str]:
    """Return the universal chain for ``(event, matcher)``.

    Used for emit-or-skip decisions: when the chain is empty we omit the
    manifest entry entirely (the runner has nothing to do for that pair).
    """
    return ordered_pipeline_for(event, matcher)


# Events whose chain applies regardless of matcher — rendered as a single
# entry with no ``matcher`` key.
_CLAUDE_DEFAULT_ONLY_EVENTS = {
    "SessionStart",
    "SessionEnd",
    "Stop",
    "UserPromptSubmit",
}
def render_claude_hooks_block() -> dict:
    """Render the Claude ``settings.json`` ``hooks`` block.

    Returns a dict keyed by event type whose values are lists of
    ``{matcher?, hooks: [{command, type}]}`` entries. Each entry contains
    exactly one runner command; matcher is omitted when the event applies
    session-wide.
    """
    block: dict[str, list[dict]] = {}
    for event in HOOK_ORDERING.keys():
        entries: list[dict] = []
        if event in _CLAUDE_DEFAULT_ONLY_EVENTS:
            if _claude_chain_for(event, "_default"):
                entries.append({"hooks": [_claude_hook_entry(event)]})
        else:
            for matcher in matchers_for(event):
                if matcher == "_default":
                    if _claude_chain_for(event, matcher):
                        entries.append({"hooks": [_claude_hook_entry(event)]})
                    continue
                # Codex-only matcher; skip when not applicable to Claude.
                if matcher == "apply_patch":
                    continue
                if not _claude_chain_for(event, matcher):
                    continue
                entries.append(
                    {
                        "hooks": [_claude_hook_entry(event)],
                        "matcher": matcher,
                    }
                )
            # PostToolUse / PostToolUseFailure declare a default chain that
            # fans out across each Claude tool matcher. Mirror the historical
            # Claude settings.json shape: emit one entry per tool matcher
            # (Bash / Write / Edit / Read) carrying the same runner command.
            if event in {"PostToolUse", "PostToolUseFailure"}:
                default_chain = _claude_chain_for(event, "_default")
                already_matchers = {
                    e.get("matcher") for e in entries if "matcher" in e
                }
                for tool_matcher in ("Bash", "Write", "Edit", "Read"):
                    if tool_matcher in already_matchers:
                        continue
                    if not default_chain:
                        continue
                    entries.append(
                        {
                            "hooks": [_claude_hook_entry(event)],
                            "matcher": tool_matcher,
                        }
                    )
        if entries:
            block[event] = entries
    return block


# ---------------------------------------------------------------------------
# Codex hooks.json — runner-per-event rendering
# ---------------------------------------------------------------------------

# Codex routes every event through the same stable Yoke CLI boundary. The
# CLI owns whether evaluation runs against local Yoke code or a cloud
# transport, so project hook configs no longer inject a repo-root PYTHONPATH.

_CODEX_VERB_BY_EVENT = {
    "SessionStart": "SessionStart",
    "UserPromptSubmit": "UserPromptSubmit",
    "PreToolUse": "PreToolUse",
    "PermissionRequest": "PreToolUse",
    "PostToolUse": "PostToolUse",
    "Stop": "Stop",
}
# Codex hook subprocesses do not reliably inherit ``CODEX_THREAD_ID`` from the
# Codex Desktop launcher, so :func:`detect_executor` would otherwise fall back
# to the Claude family and store ``executor=claude-code`` /
# ``provider=anthropic`` on the session row and ``context.executor=claude`` on
# every ``HookDispatchTelemetry`` envelope. Pin the coarse Codex family signal
# (``codex``) plus the inference provider (``openai``) directly in the
# generated hook command so :func:`detect_executor` returns ``codex`` and
# :func:`detect_provider` returns ``openai`` regardless of what the Codex
# parent process exported.
_CODEX_IDENTITY_ENV = "YOKE_EXECUTOR=codex YOKE_PROVIDER=openai"


def _codex_command(event_name: str) -> str:
    return (
        "/bin/zsh -lc '"
        f"env {_CODEX_IDENTITY_ENV} {_YOKE_HOOK_EVALUATE} {event_name}"
        "'"
    )

# Codex matcher composition: PreToolUse and PostToolUse fan out into the
# Bash matcher plus the apply_patch|Write|Edit composite matcher. Other
# events use either no matcher or the SessionStart startup|resume matcher.

_CODEX_PRE_POST_TOOL_MATCHERS = (
    "Bash",
    "apply_patch|Write|Edit",
)

_CODEX_PERMISSION_MATCHER = "apply_patch|Write|Edit"
_CODEX_SESSION_START_MATCHER = "startup|resume"


def _codex_entry(matcher: str | None, verb: str) -> dict:
    entry: dict = {"hooks": [{"type": "command", "command": _codex_command(verb)}]}
    if matcher is not None:
        # Insert matcher before hooks for stable output.
        entry = {"matcher": matcher, "hooks": entry["hooks"]}
    return entry


def render_codex_hooks_block() -> dict:
    """Render the Codex ``hooks.json`` ``hooks`` block.

    Codex emits one adapter-verb entry per event/matcher pair. Event ordering
    matches the historical hand-authored shape so the rendered file matches
    the post-task-001 content byte-for-byte once written canonically.
    """
    block: dict[str, list[dict]] = {}
    # SessionStart — startup|resume matcher.
    block["SessionStart"] = [
        _codex_entry(_CODEX_SESSION_START_MATCHER, _CODEX_VERB_BY_EVENT["SessionStart"])
    ]
    # UserPromptSubmit — no matcher.
    block["UserPromptSubmit"] = [
        _codex_entry(None, _CODEX_VERB_BY_EVENT["UserPromptSubmit"])
    ]
    # PreToolUse — Bash + apply_patch|Write|Edit composite.
    block["PreToolUse"] = [
        _codex_entry(m, _CODEX_VERB_BY_EVENT["PreToolUse"])
        for m in _CODEX_PRE_POST_TOOL_MATCHERS
    ]
    # PermissionRequest — apply_patch|Write|Edit composite only.
    block["PermissionRequest"] = [
        _codex_entry(_CODEX_PERMISSION_MATCHER, _CODEX_VERB_BY_EVENT["PermissionRequest"])
    ]
    # PostToolUse — Bash + apply_patch|Write|Edit composite.
    block["PostToolUse"] = [
        _codex_entry(m, _CODEX_VERB_BY_EVENT["PostToolUse"])
        for m in _CODEX_PRE_POST_TOOL_MATCHERS
    ]
    # Stop — no matcher.
    block["Stop"] = [_codex_entry(None, _CODEX_VERB_BY_EVENT["Stop"])]
    return block
