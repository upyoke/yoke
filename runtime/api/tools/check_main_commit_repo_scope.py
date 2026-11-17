"""Probe installed main-commit hooks with scratch and isolated main indexes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


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


def main():
    root = Path(git(Path.cwd(), "rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    with tempfile.TemporaryDirectory(prefix="main-commit-scope-") as scratch:
        scratch = Path(scratch)
        repo = scratch / "repo"
        repo.mkdir()
        git(repo, "init", "-b", "main")
        (repo / "source.py").write_text("value = 1\n")
        git(repo, "add", "source.py")
        allowed = evaluate(repo)
        if allowed.returncode:
            raise RuntimeError(
                f"scratch commit hook refused: {allowed.stdout} {allowed.stderr}; "
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
        denied = evaluate(root, env=env)
        output = denied.stdout + denied.stderr
        if not denied.returncode or "Implementation commit on main" not in output:
            raise RuntimeError(
                f"project main hook did not give expected denial: {output}; "
                "ensure this session has an active project lane and rerun after deployed hooks converge"
            )
        refs = re.findall(r"- ([A-Z][A-Z0-9]*-\d+):", output)
        if not refs:
            raise RuntimeError("denial listed no item refs; inspect the hook output and repair")
        roster = run(
            ["yoke", "items", "overview", "list", "--limit", "1000", "--json"],
            cwd=root,
        )
        if roster.returncode:
            raise RuntimeError(
                f"item roster unavailable: {roster.stderr}; restore control-plane access and rerun"
            )
        rows = json.loads(roster.stdout)["result"]["rows"]
        expected = {
            row["public_ref"]
            for row in rows if not row.get("terminal")
            and any(
                os.path.normcase(os.path.normpath(lane.get("path", ""))).startswith(
                    os.path.normcase(str(root / ".worktrees")) + os.sep
                )
                for lane in row.get("worktrees", [])
            )
        }
        if not set(refs).issubset(expected):
            raise RuntimeError(
                f"denial names foreign items: {set(refs) - expected}; "
                "repair repository filtering and rerun"
            )
        print(f"Project main implementation commit: denied with only matching items {refs}")
        print(output)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"main_commit_scope_probe_failed: {exc}") from None
