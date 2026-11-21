"""A tiny three-layer map and git repository for the architecture edge tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

SRC = "packages/yoke-core/src/yoke_core"

MODEL = {
    "layers": [
        {"id": "low", "may_depend_on": [], "forbidden_edges": ["high"]},
        {"id": "mid", "may_depend_on": ["low"], "forbidden_edges": []},
        {"id": "high", "may_depend_on": ["low", "mid"], "forbidden_edges": []},
    ],
    "domains": [
        {
            "id": "app",
            "path_roots": [
                {"glob": f"{SRC}/low/**", "layer": "low"},
                {"glob": f"{SRC}/mid/**", "layer": "mid"},
                {"glob": f"{SRC}/high/**", "layer": "high"},
            ],
        }
    ],
    "exemptions": [{"glob": f"{SRC}/tests/**", "family": "architecture_test_surface"}],
    "package_roots": {
        "yoke_core": [{"root": "packages/yoke-core/src", "layout": "package_under_root"}]
    },
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def write(repo: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        target = repo / path
        if text is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def commit(repo: Path, files: dict[str, str], message: str = "change") -> str:
    write(repo, files)
    git(repo, "add", "-A", "-f")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def init_repo(repo: Path, files: dict[str, str]) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    return commit(repo, files, "base")


def model_response(model=MODEL, *, success=True, code="", message=""):
    if not success:
        return SimpleNamespace(
            success=False, result=None, error=SimpleNamespace(code=code, message=message)
        )
    entries = [{"attachment": "project", "payload": model}] if model is not None else []
    return SimpleNamespace(success=True, result={"entries": entries}, error=None)


def dispatch_returning(response, calls=None):
    def dispatch(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return response

    return dispatch
