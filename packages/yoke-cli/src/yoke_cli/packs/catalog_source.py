"""Select which Pack catalog a Pack command reads, and read pre-release source.

``served`` is the catalog of the connected control plane's installed release.
``lane`` is the Yoke source checkout ``yoke dev run`` bound, so an author can
install a Pack version before it merges. ``commit:SHA`` is a commit already
merged into the Yoke default branch, so a consumer project can adopt a Pack
version before a release serves it. Pre-release source is read here and
submitted to ``packs.bundle.render``; the server still renders it.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
from typing import Any, Mapping

from yoke_cli.packs.errors import PackClientError
from yoke_contracts.install_binding import (
    SOURCE_DEV_RUN_ROOT_ENV,
    is_yoke_source_checkout,
    source_checkout_root,
)
from yoke_contracts.packs import (
    PACK_CATALOG_COMMIT,
    PACK_CATALOG_LANE,
    PACK_CATALOG_SERVED,
    PACKS_SOURCE,
)

CATALOG_CHOICES_TEXT = "served, lane, or commit:SHA"


@dataclass(frozen=True)
class PackCatalog:
    kind: str
    checkout: Path | None = None
    commit: str | None = None

    @property
    def served(self) -> bool:
        return self.kind == PACK_CATALOG_SERVED

    def source(self) -> dict[str, str]:
        """The receipt/wire source record for Pack versions read here."""
        if self.served:
            return {"kind": self.kind}
        return {"kind": self.kind, "commit": str(self.commit)}

    def describe(self) -> dict[str, str]:
        """The visible catalog identity printed with every Pack report."""
        described = self.source()
        if self.checkout is not None:
            described["checkout"] = str(self.checkout)
        return described

    def descriptors(self) -> dict[str, dict[str, Any]]:
        """Every Pack descriptor this pre-release catalog carries, by slug."""
        members = self._read_tree(*self._descriptor_paths())
        descriptors: dict[str, dict[str, Any]] = {}
        for relative, content in sorted(members.items()):
            parts = relative.split("/")
            if len(parts) == 2 and parts[1] == "pack.json":
                descriptors[parts[0]] = _parse_descriptor(relative, content)
        return descriptors

    def pack_files(self, pack: str) -> list[dict[str, str]]:
        """One Pack's whole source tree, ``packs/``-relative and base64-encoded.

        The whole tree travels because the server validates every version a
        descriptor declares exactly as it validates the served catalog.
        """
        members = self._read_tree(f"{PACKS_SOURCE}/{pack}")
        if f"{pack}/pack.json" not in members:
            raise PackClientError(
                f"pack-catalog-missing-pack: Pack {pack!r} is not in the "
                f"{self.label()}; check the slug with `yoke packs list --catalog "
                f"{self.spec()}`"
            )
        return [
            {"path": path, "content": base64.b64encode(content).decode("ascii")}
            for path, content in sorted(members.items())
        ]

    def label(self) -> str:
        if self.kind == PACK_CATALOG_LANE:
            return f"lane catalog at {self.checkout}"
        if self.kind == PACK_CATALOG_COMMIT:
            return f"catalog at merged commit {self.commit}"
        return "served catalog"

    def spec(self) -> str:
        return catalog_spec(self.source())

    def _descriptor_paths(self) -> list[str]:
        assert self.checkout is not None
        if self.kind == PACK_CATALOG_LANE:
            return [
                path.relative_to(self.checkout).as_posix()
                for path in sorted((self.checkout / PACKS_SOURCE).glob("*/pack.json"))
            ]
        listing = _git_text(
            self.checkout,
            "ls-tree",
            "-r",
            "--name-only",
            str(self.commit),
            "--",
            PACKS_SOURCE,
        )
        return [
            line
            for line in listing.splitlines()
            if len(line.split("/")) == 3 and line.endswith("/pack.json")
        ]

    def _read_tree(self, *relatives: str) -> dict[str, bytes]:
        """Files under checkout-relative paths, keyed ``packs/``-relative."""
        assert self.checkout is not None
        prefix = f"{PACKS_SOURCE}/"
        if not relatives:
            return {}
        if self.kind == PACK_CATALOG_LANE:
            files: dict[str, bytes] = {}
            for relative in relatives:
                base = self.checkout / relative
                paths = [base] if base.is_file() else sorted(base.rglob("*"))
                for path in paths:
                    if path.is_file():
                        key = path.relative_to(self.checkout).as_posix()[len(prefix) :]
                        files[key] = path.read_bytes()
            return files
        listed = _git_text(
            self.checkout,
            "ls-tree",
            "-r",
            "--name-only",
            str(self.commit),
            "--",
            *relatives,
        )
        if not listed:
            return {}
        archive = _git(
            self.checkout, "archive", "--format=tar", str(self.commit), "--", *relatives
        )
        files: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            for member in bundle.getmembers():
                if member.isfile():
                    handle = bundle.extractfile(member)
                    assert handle is not None
                    files[member.name[len(prefix) :]] = handle.read()
        return files


def catalog_spec(source: Mapping[str, str]) -> str:
    """The ``--catalog`` value that reads the catalog a source record names."""
    if source.get("kind") == PACK_CATALOG_COMMIT:
        return f"{PACK_CATALOG_COMMIT}:{source['commit']}"
    return str(source["kind"])


def resolve_catalog(
    spec: str | None, *, yoke_checkout: str | None = None
) -> PackCatalog:
    """Resolve ``--catalog``; omitted means lane under ``yoke dev run``, else served."""

    dev_run_root = os.environ.get(SOURCE_DEV_RUN_ROOT_ENV, "").strip()
    requested = (
        spec or (PACK_CATALOG_LANE if dev_run_root else PACK_CATALOG_SERVED)
    ).strip()
    if requested == PACK_CATALOG_SERVED:
        return PackCatalog(kind=PACK_CATALOG_SERVED)
    if requested == PACK_CATALOG_LANE:
        if not dev_run_root:
            raise PackClientError(
                "pack-catalog-lane-unavailable: --catalog lane reads the Yoke source "
                "lane `yoke dev run` binds; rerun as `yoke dev run -- yoke packs ...` "
                "from a claimed Yoke lane, or name a merged commit with --catalog commit:SHA"
            )
        root = Path(dev_run_root).resolve()
        return PackCatalog(
            kind=PACK_CATALOG_LANE,
            checkout=root,
            commit=_git_text(root, "rev-parse", "HEAD"),
        )
    if requested.startswith(f"{PACK_CATALOG_COMMIT}:"):
        checkout = _commit_checkout(yoke_checkout, dev_run_root)
        return PackCatalog(
            kind=PACK_CATALOG_COMMIT,
            checkout=checkout,
            commit=_merged_commit(checkout, requested.split(":", 1)[1].strip()),
        )
    raise PackClientError(
        f"pack-catalog-invalid: --catalog {requested!r} is not one of {CATALOG_CHOICES_TEXT}"
    )


def _commit_checkout(explicit: str | None, dev_run_root: str) -> Path:
    if explicit:
        candidate: Path | None = Path(explicit).expanduser().resolve()
    elif dev_run_root:
        candidate = Path(dev_run_root).resolve()
    else:
        candidate = source_checkout_root(__file__)
    if candidate is None or not is_yoke_source_checkout(candidate):
        shown = candidate or "<none: this yoke runs from a packaged install>"
        raise PackClientError(
            f"pack-catalog-checkout-missing: --catalog commit:SHA reads Pack source "
            f"from a Yoke source checkout, and {shown} is not one; pass "
            "--yoke-checkout PATH naming a clone of the Yoke repository"
        )
    return candidate


def _merged_commit(checkout: Path, raw: str) -> str:
    if not raw:
        raise PackClientError(
            "pack-catalog-invalid: --catalog commit:SHA names no commit"
        )
    try:
        commit = _git_text(
            checkout, "rev-parse", "--verify", "--quiet", f"{raw}^{{commit}}"
        )
    except PackClientError as exc:
        raise PackClientError(
            f"pack-catalog-commit-unknown: {raw!r} is not a commit in {checkout}; "
            f"run `git -C {checkout} fetch origin` if it merged after the last fetch"
        ) from exc
    try:
        default_ref = _git_text(
            checkout, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"
        )
    except PackClientError as exc:
        raise PackClientError(
            f"pack-catalog-default-branch-unknown: {checkout} records no origin "
            f"default branch; run `git -C {checkout} remote set-head origin --auto`"
        ) from exc
    merged = subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "merge-base",
            "--is-ancestor",
            commit,
            default_ref,
        ],
        capture_output=True,
        check=False,
    )
    if merged.returncode != 0:
        branch = default_ref.removeprefix("refs/remotes/")
        raise PackClientError(
            f"pack-catalog-commit-unmerged: {commit} is not merged into {branch}; "
            "pre-release Pack installs name a merged commit (use `yoke dev run` "
            f"with --catalog lane for unmerged work), or run `git -C {checkout} "
            "fetch origin` if it merged after the last fetch"
        )
    return commit


def _parse_descriptor(relative: str, content: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackClientError(
            f"Pack descriptor {relative} is unreadable: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise PackClientError(f"Pack descriptor {relative} root must be an object")
    return parsed


def _git(checkout: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(checkout), *args], capture_output=True, check=False
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise PackClientError(f"git {' '.join(args)} failed in {checkout}: {detail}")
    return completed.stdout


def _git_text(checkout: Path, *args: str) -> str:
    return _git(checkout, *args).decode("utf-8").strip()


__all__ = ["CATALOG_CHOICES_TEXT", "PackCatalog", "catalog_spec", "resolve_catalog"]
