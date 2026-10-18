"""Positive ownership proof and durable recovery for interrupted installs."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from yoke_cli.project_install import checkout_gate
from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_safe_bundle_paths,
    assert_resolved_targets_within,
    sha256_text,
)

PENDING_REL = ".yoke/install-pending.json"


def atomic_text(path: Path, content: str) -> None:
    name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_file() and not path.is_symlink():
            os.chmod(name, path.stat().st_mode & 0o777)
        os.replace(name, path)
    except OSError as exc:
        raise ProjectInstallError(
            f"install_write_failed: could not atomically write {path}. "
            "Restore filesystem space/permissions, then rerun yoke project "
            "refresh; the prior file and interrupted-apply record are preserved."
        ) from exc
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def pending_record(root: Path) -> dict[str, Any]:
    assert_resolved_targets_within(root, [PENDING_REL], context="install recovery")
    path = root / PENDING_REL
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or set(value) != {"files", "checkout"}:
            raise ValueError("invalid recovery record")
        files = value["files"]
        checkout = value["checkout"]
        if not isinstance(files, dict) or not all(
            isinstance(k, str)
            and isinstance(v, str)
            and len(v) == 64
            and all(c in "0123456789abcdef" for c in v)
            for k, v in files.items()
        ):
            raise ValueError("invalid file digests")
        assert_safe_bundle_paths(files)
        if not isinstance(checkout, dict) or not all(
            isinstance(k, str)
            and isinstance(v, list)
            and v
            and all(isinstance(s, str) for s in v)
            for k, v in checkout.items()
        ):
            raise ValueError("invalid checkout states")
        assert_resolved_targets_within(
            root, checkout, context="install recovery checkout"
        )
        return value
    except (OSError, ValueError) as exc:
        raise ProjectInstallError(
            "install_recovery_unreadable: interrupted-apply record cannot be read. "
            "Preserved files; restore .yoke/install-pending.json from the failed "
            "apply or ask the control-plane operator to reconcile the install."
        ) from exc


def pending(root: Path) -> dict[str, str]:
    return pending_record(root).get("files", {})


class GitOwnership:
    """Read the last path writer once; compare bytes against its committed blob."""

    def __init__(self, root: Path, *, revision: str = "HEAD"):
        self.root = root
        self.writers: dict[str, str] = {}
        result = checkout_gate.run_git(
            root,
            "log",
            "--format=%x00%H%x00%s",
            "--name-only",
            "--no-renames",
            revision,
            "--",
            ".agents/skills/yoke",
            ".yoke/docs",
            ".claude/agents",
            ".codex/agents",
            ".cursor/agents",
            "AGENTS.md",
        )
        if result.returncode:
            return
        commit = ""
        for line in result.stdout.splitlines():
            if line.startswith("\0"):
                _, sha, subject = line.split("\0", 2)
                commit = sha if _installer_subject(subject) else ""
            elif line.strip() and line not in self.writers:
                self.writers[line] = commit

    def proves(self, rel: str, digest: str) -> bool:
        commit = self.writers.get(rel)
        if not commit:
            return False
        blob = checkout_gate.run_git(self.root, "show", f"{commit}:{rel}")
        return blob.returncode == 0 and sha256_text(blob.stdout) == digest


def _installer_subject(subject: str) -> bool:
    # History is ownership evidence, including the installer's earlier wording.
    return bool(
        re.fullmatch(
            r"(?:Install Yoke operating layer |Refresh (?:the )?installed Yoke operating layer to )[^\s]+",
            subject,
        )
    )


def plan(root: Path, bundle: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    """Refuse real edits; missing files and positively proven drift are repairable."""
    incoming = {e["path"]: sha256_text(e["content"]) for e in bundle["files"]}
    previous = dict(prior.get("files") or {})
    interrupted = pending(root)
    missing, changed = [], []
    proof = None
    from yoke_cli.project_install.released_bundle_files import ReleasedBundleFiles

    archives = ReleasedBundleFiles()
    for rel in sorted(set(previous) | set(incoming)):
        baseline = previous.get(rel)
        target = root / rel
        if not target.is_file():
            if rel in previous:
                missing.append(rel)
            continue
        try:
            content = target.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ProjectInstallError(
                f"install_drift_unreadable: {rel} cannot be compared. "
                "Restore its recorded UTF-8 content, then rerun project refresh."
            ) from exc
        from yoke_cli.project_install.recovery_checkout import text_digests

        digests = text_digests(content)
        if baseline in digests:
            continue
        changed.append(rel)
        installer_digests = {incoming.get(rel), interrupted.get(rel)}
        matched = next((digest for digest in digests if digest in installer_digests), None)
        if matched is not None:
            previous[rel] = matched
            continue
        if proof is None:
            proof = GitOwnership(root)
        if any(proof.proves(rel, digest) for digest in digests) or archives.proves(
            rel, target.read_text(encoding="utf-8")
        ):
            previous[rel] = sha256_text(content)
            continue
        raise ProjectInstallError(
            f"install_drift_local_edits: {rel} differs from the install record "
            "and has no bundle or installer-history proof. Preserved all files. "
            "Save the local edits outside installer-owned paths, restore the "
            "recorded release bytes, then rerun yoke project refresh."
        )
    return {
        "missing": sorted(missing),
        "changed": sorted(changed),
        "interrupted": bool(interrupted),
        "candidate": incoming,
        "prior_files": previous,
    }


def begin(root: Path, plan: dict[str, Any]) -> None:
    # Recovery is machine-local even when an older serving bundle lacks its ignore.
    if checkout_gate.is_git_checkout(root):
        result = checkout_gate.run_git(root, "rev-parse", "--git-path", "info/exclude")
        if result.returncode:
            raise ProjectInstallError(
                "install_recovery_ignore_unreadable: repair Git metadata, then rerun refresh; files were preserved"
            )
        exclude = Path(result.stdout.strip())
        if not exclude.is_absolute():
            exclude = root / exclude
        text = exclude.read_text() if exclude.is_file() else ""
        entry = "/" + PENDING_REL
        if entry not in text.splitlines():
            atomic_text(
                exclude,
                text
                + ("\n" if text and not text.endswith("\n") else "")
                + entry
                + "\n",
            )
    value = {"files": plan["candidate"], "checkout": plan["checkout"]}
    previous = pending_record(root)
    if previous.get("files") == value["files"]:
        for rel, states in previous["checkout"].items():
            value["checkout"][rel] = sorted(
                set(states) | set(value["checkout"].get(rel, []))
            )
    atomic_text(root / PENDING_REL, json.dumps(value, sort_keys=True) + "\n")


def record_manifest(root: Path, content: str) -> None:
    """Authorize the exact completed manifest before its atomic replacement."""
    value = pending_record(root)
    if not value:
        return
    rel = ".yoke/install-manifest.json"
    states = set(value["checkout"].get(rel, []))
    states.add(sha256_text(content))
    value["checkout"][rel] = sorted(states)
    atomic_text(root / PENDING_REL, json.dumps(value, sort_keys=True) + "\n")


def finish(root: Path, hashes: dict[str, str], *, clear_pending: bool = True) -> None:
    for rel, expected in hashes.items():
        target = root / rel
        if (
            not target.is_file()
            or sha256_text(target.read_bytes().decode("utf-8")) != expected
        ):
            raise ProjectInstallError(
                f"install_apply_incomplete: {rel} does not match the completed "
                "install record. Rerun yoke project refresh; the interrupted "
                "apply record was retained."
            )
    if clear_pending:
        (root / PENDING_REL).unlink(missing_ok=True)


def recoverable_checkout(root: Path) -> bool:
    """Only exact planned states bypass the ordinary dirty gate."""
    from yoke_cli.project_install.recovery_checkout import states

    expected = pending_record(root).get("checkout", {})
    if not expected:
        return False
    paths = [
        checkout_gate._porcelain_path(line) for line in checkout_gate.porcelain(root)
    ]
    for rel in checkout_gate.discovery_commit_paths(root, paths):
        if rel == PENDING_REL:
            continue
        try:
            if states(root / rel).isdisjoint(expected.get(rel, [])):
                return False
        except (OSError, UnicodeError):
            return False
    return True


def removed_owned_paths(root: Path, existing: list[str]) -> list[str]:
    """Recover positively owned deletions after an earlier apply lost its record."""
    from yoke_cli.project_install import checkout_gate
    from yoke_cli.project_install.released_bundle_files import ReleasedBundleFiles

    proof, released = None, ReleasedBundleFiles()
    removed = []
    for line in checkout_gate.porcelain(root):
        rel = checkout_gate._porcelain_path(line)
        if (root / rel).exists() or rel in existing:
            continue
        if not rel.startswith(
            (
                ".agents/skills/yoke/",
                ".yoke/docs/",
                ".claude/agents/",
                ".codex/agents/",
                ".cursor/agents/",
            )
        ):
            continue
        blob = checkout_gate.run_git(root, "show", f"HEAD:{rel}")
        if blob.returncode:
            continue
        if proof is None:
            proof = GitOwnership(root)
        if proof.proves(rel, sha256_text(blob.stdout)) or released.proves(
            rel, blob.stdout
        ):
            removed.append(rel)
    return removed
