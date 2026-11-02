"""Prove released bytes from packaged hashes or annotated source history."""

from __future__ import annotations

import hashlib
import json
from functools import cache
from importlib.resources import files
from yoke_cli.project_install.files import ProjectInstallError, sha256_text

from yoke_cli.project_install import checkout_gate
from yoke_contracts.install_binding import source_checkout_root


class ReleasedBundleFiles:
    """Packaged evidence and source release history share exact content proof."""

    def __init__(self):
        self.root = source_checkout_root(__file__)
        self.proven: dict[tuple[str, str], bool] = {}

    def proves(self, rel: str, content: str) -> bool:
        canonical = _source_path(rel)
        if canonical is None:
            return False
        key = catalogue_key(canonical)
        if sha256_text(content) in _catalogue().get(key, []):
            return True
        if self.root is None:
            return False
        raw = content.encode("utf-8")
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        key = (canonical, blob)
        if key in self.proven:
            return self.proven[key]
        self.proven[key] = self._in_release(canonical, blob)
        return self.proven[key]

    def _in_release(self, canonical: str, blob: str) -> bool:
        assert self.root is not None
        changes = checkout_gate.run_git(
            self.root,
            "log",
            "--all",
            f"--find-object={blob}",
            "--format=%H",
            "--",
            canonical,
        )
        if changes.returncode:
            return False
        for commit in changes.stdout.splitlines():
            at_commit = checkout_gate.run_git(
                self.root, "rev-parse", f"{commit}:{canonical}"
            )
            if at_commit.returncode or at_commit.stdout.strip() != blob:
                continue
            tags = checkout_gate.run_git(
                self.root,
                "for-each-ref",
                "--contains",
                commit,
                "--format=%(refname) %(objecttype)",
                "refs/tags/v*",
            )
            if tags.returncode:
                return False
            for line in tags.stdout.splitlines():
                tag, kind = line.split()
                if kind != "tag":
                    continue
                released = checkout_gate.run_git(
                    self.root, "rev-parse", f"{tag}:{canonical}"
                )
                if released.returncode == 0 and released.stdout.strip() == blob:
                    return True
        return False


def catalogue_key(canonical: str) -> str:
    if canonical.startswith(".agents/skills/yoke/"):
        return "skills/" + canonical.removeprefix(".agents/skills/yoke/")
    if canonical.startswith("docs/public/"):
        return "docs/" + canonical.removeprefix("docs/public/")
    return canonical


def _source_path(rel: str) -> str | None:
    for harness in ("agents", "claude", "codex", "cursor"):
        prefix = f".{harness}/skills/yoke/"
        if rel.startswith(prefix):
            return ".agents/skills/yoke/" + rel.removeprefix(prefix)
    if rel.startswith(".yoke/docs/"):
        return "docs/public/" + rel.removeprefix(".yoke/docs/")
    for harness in ("claude", "codex", "cursor"):
        prefix = f".{harness}/agents/"
        if rel.startswith(prefix):
            return f"runtime/harness/{harness}/agents/" + rel.removeprefix(prefix)
    return None


@cache
def _catalogue() -> dict[str, list[str]]:
    try:
        value = json.loads(
            files("yoke_cli.project_install")
            .joinpath("released_bundle_hashes.json")
            .read_text()
        )
        if not isinstance(value, dict) or not all(
            isinstance(k, str)
            and isinstance(v, list)
            and all(
                isinstance(d, str)
                and len(d) == 64
                and all(c in "0123456789abcdef" for c in d)
                for d in v
            )
            for k, v in value.items()
        ):
            raise ValueError("invalid release hashes")
        return value
    except (OSError, ValueError) as exc:
        raise ProjectInstallError(
            "install_release_catalogue_unreadable: immutable release ownership "
            "evidence is missing or corrupt. Reinstall the CLI with the public "
            "installer, then rerun project refresh; all project files were preserved."
        ) from exc
