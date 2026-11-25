"""Remove Git shims from checkouts installed by older Yoke releases."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from yoke_contracts.project_contract.install_error import ProjectInstallError
from yoke_contracts.refusal_recovery import compose_refusal

LEGACY_HASH_KEY = "git_hook" "_hashes"
_NAMES = (
    "pre-commit", "pre-merge-commit", "post-commit", "post-merge",
    "post-rewrite", "post-checkout",
)
_YOKE_EXEC = re.compile(
    r'exec (?:(?:"\$yoke_bin"|yoke) git [a-z-]+ "\$@"'
    r'|python3 -m yoke_core\.[\w.]+(?: [^\n]*)?)'
)


def remove(
    root: Path,
    *,
    manifest: dict | None = None,
    warnings: list[str] | None = None,
) -> list[str]:
    """Remove recognized shims in Git's common metadata directory."""
    from yoke_cli.project_install import checkout_gate

    path = root / ".git"
    if path.is_symlink() or not path.exists():
        return []
    removed = []
    try:
        result = checkout_gate.run_git(root, "rev-parse", "--git-common-dir")
        if result.returncode or not result.stdout.strip():
            raise OSError(result.stderr.strip() or "Git returned no common directory")
        hooks = root / result.stdout.strip() / "hooks"
        if hooks.is_symlink():
            return []
        hashes = (manifest or {}).get(LEGACY_HASH_KEY, {})
        if not isinstance(hashes, dict):
            hashes = {}
        for name in _NAMES:
            path = hooks / name
            if path.is_symlink() or not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            lines = content.rstrip().splitlines()
            marker = f"# yoke-{name} hook installed by `yoke project install`"
            recorded = hashes.get(f".git/hooks/{name}")
            owned = recorded and recorded == hashlib.sha256(content.encode()).hexdigest()
            shipped = (
                marker in lines and lines[0] == "#!/bin/sh"
                and _YOKE_EXEC.fullmatch(lines[-1])
            )
            if owned or shipped:
                path.unlink(missing_ok=True)
                removed.append(name)
            elif marker in lines and warnings is not None:
                warnings.append(f"Edited Yoke Git hook at {path}; remove it by hand.")
    except (OSError, UnicodeError) as exc:
        raise ProjectInstallError(
            compose_refusal(
                f"retired_git_hook_cleanup_failed: {path}: {exc}",
                recovery="Repair Git metadata or permissions, then retry the command.",
            )
        ) from exc
    return removed
