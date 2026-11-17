"""Probe installed main-commit hooks with scratch and isolated main indexes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

LANE_SEGMENT = "/.worktrees/"


def run(args, *, cwd, env=None, stdin=None):
    return subprocess.run(
        args, cwd=cwd, env=env, input=stdin, text=True,
        capture_output=True, timeout=60,
    )


def git(cwd, *args, env=None):
    result = run(["git", *args], cwd=cwd, env=env)
    if result.returncode:
        raise RuntimeError(f"git probe failed: {result.stderr}; repair fixture and rerun")
    return result.stdout.strip()


def evaluate(cwd, *, env=None):
    payload = {
        "cwd": str(cwd), "tool_name": "Bash",
        "tool_input": {"command": "git commit -m repository-scope-probe"},
    }
    return run(
        ["yoke", "hook", "evaluate", "PreToolUse"], cwd=cwd,
        env=env, stdin=json.dumps(payload),
    )


def hook_verdict(result):
    """Return ``(denied, reason)`` from any harness's hook wire shape.

    Claude denies with exit 2 and the reason on stderr. Codex denies with a
    ``hookSpecificOutput.permissionDecision`` JSON envelope and exit 0; Cursor
    with a ``permission`` JSON body and exit 0. Empty stdout or a context-only
    envelope on exit 0 allows.
    """
    if result.returncode == 2:
        return True, result.stderr + result.stdout
    if result.returncode:
        raise RuntimeError(
            f"hook evaluate crashed with exit {result.returncode}: "
            f"{result.stdout} {result.stderr}; repair the installed hook and rerun"
        )
    text = result.stdout.strip()
    if not text:
        return False, ""
    try:
        body = json.loads(text)
    except ValueError:
        raise RuntimeError(
            f"hook evaluate printed non-JSON stdout on exit 0: {text}; "
            "repair the hook wire output and rerun"
        ) from None
    envelope = body.get("hookSpecificOutput") or {}
    if envelope.get("permissionDecision") == "deny":
        return True, envelope.get("permissionDecisionReason", "")
    if body.get("permission") == "deny":
        return True, body.get("agent_message") or body.get("user_message", "")
    return False, ""


def normalize_root(path):
    """Compare repository roots across POSIX and Windows spellings."""
    text = str(path).replace("\\", "/")
    if os.path.exists(text):
        text = os.path.realpath(text).replace("\\", "/")
    if re.match(r"^[A-Za-z]:", text):
        text = text[0].lower() + text[1:]
    return text.rstrip("/")


def lane_repo_root(lane_path):
    text = str(lane_path).replace("\\", "/")
    if LANE_SEGMENT not in text:
        return None
    return normalize_root(text.split(LANE_SEGMENT, 1)[0])


def item_lane_roots(item):
    return {
        root
        for lane in item.get("worktrees") or []
        if lane.get("state") == "active" and not lane.get("released_at")
        for root in [lane_repo_root(lane.get("path", ""))]
        if root
    }


def read_item(ref, cwd):
    result = run(["yoke", "items", "detail", "get", ref, "--include", "", "--json"], cwd=cwd)
    if result.returncode:
        raise RuntimeError(
            f"item {ref} unreadable: {result.stdout} {result.stderr}; "
            "restore control-plane access and rerun"
        )
    return json.loads(result.stdout)["result"]["item"]


def foreign_refs(refs, root, read):
    """Return the denied refs with no active lane recorded in ``root``."""
    target = normalize_root(root)
    return sorted(ref for ref in refs if target not in item_lane_roots(read(ref)))


def main():
    # From the QA candidate (a linked worktree) the common dir names the real
    # project checkout, whose recorded lanes the guard judges.
    root = Path(git(Path.cwd(), "rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    with tempfile.TemporaryDirectory(prefix="main-commit-scope-") as scratch:
        scratch = Path(scratch)
        repo = scratch / "repo"
        repo.mkdir()
        git(repo, "init", "-b", "main")
        git(repo, "-c", "user.name=Scope probe", "-c", "user.email=probe@example.invalid",
            "commit", "--allow-empty", "-m", "initial")
        (repo / "source.py").write_text("value = 1\n")
        git(repo, "add", "source.py")
        denied, reason = hook_verdict(evaluate(repo))
        if denied:
            raise RuntimeError(
                f"scratch commit hook refused: {reason}; "
                "inspect the installed hook denial and repair before rerunning"
            )
        git(repo, "-c", "user.name=Scope probe", "-c", "user.email=probe@example.invalid",
            "commit", "-m", "scratch repository commit")
        print("Scratch main-branch implementation commit: allowed and committed")

        # Keep the checkout and its real index untouched. Git subprocesses in the
        # installed hook inherit this alternative index.
        env = dict(os.environ, GIT_INDEX_FILE=str(scratch / "main-index"))
        git(root, "read-tree", "HEAD", env=env)
        tracked = git(root, "ls-files").splitlines()
        source = next(path for path in tracked if path.endswith(".py"))
        # Reuse a committed blob with different content; no shared objects change.
        original = git(root, "rev-parse", f"HEAD:{source}")
        blob = next(
            git(root, "rev-parse", f"HEAD:{path}")
            for path in tracked if path.endswith(".py")
            and git(root, "rev-parse", f"HEAD:{path}") != original
        )
        git(root, "update-index", "--cacheinfo", f"100644,{blob},{source}", env=env)
        denied, reason = hook_verdict(evaluate(root, env=env))
        if not denied or "Implementation commit on main" not in reason:
            raise RuntimeError(
                f"project main hook did not give expected denial: {reason}; "
                "ensure this session has an active project lane and rerun after deployed hooks converge"
            )
        refs = re.findall(r"- ([A-Z][A-Z0-9]*-\d+):", reason)
        if not refs:
            raise RuntimeError("denial listed no item refs; inspect the hook output and repair")
        foreign = foreign_refs(refs, root, lambda ref: read_item(ref, root))
        if foreign:
            raise RuntimeError(
                f"denial names items with no active lane in {root}: {foreign}; "
                "repair repository filtering and rerun"
            )
        print(f"Project main implementation commit: denied with only matching items {refs}")
        print(reason)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"main_commit_scope_probe_failed: {exc}") from None
