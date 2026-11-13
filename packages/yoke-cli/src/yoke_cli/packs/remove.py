"""Preview-first removal of one installed Pack's record from a project.

Removal forgets the Pack: it drops the Pack's record from
``.yoke/packs.json`` and the server's install record for the project. Every
file the Pack used to own stays in the project, unchanged and project-owned.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import existing_project_lookup
from yoke_cli.packs.catalog_source import PackCatalog, catalog_spec
from yoke_cli.packs.errors import PackClientError
from yoke_cli.packs.receipt import (
    PackReceiptError,
    load_receipt,
    validate_receipt,
    write_receipt,
)
from yoke_cli.packs.runner_support import _fetch_bundle, _report_receipt
from yoke_contracts.packs import PACK_CATALOG_SERVED, PACK_RECEIPT_REL


def run_pack_remove(
    repo_root: str | Path | None,
    *,
    project: str,
    pack: str,
    apply: bool = False,
    session_id: str | None = None,
    catalog: PackCatalog | None = None,
) -> dict[str, Any]:
    """Preview or apply dropping *pack* from the receipt and server record.

    The removed Pack's own catalog entry is never read, so a Pack that left
    the catalog, or whose baseline can no longer be rebuilt, still removes.
    Each other installed Pack is read from *catalog* at its recorded version
    to learn its dependencies, because the receipt stores none.
    """

    root = Path(repo_root or os.getcwd()).expanduser().resolve()
    if not root.is_dir():
        raise PackClientError(f"project checkout is not a directory: {root}")
    catalog = catalog or PackCatalog(kind=PACK_CATALOG_SERVED)
    try:
        receipt = load_receipt(root)
    except PackReceiptError as exc:
        raise PackClientError(
            f"pack-receipt-invalid: {exc}; restore {PACK_RECEIPT_REL} from version "
            "control, then rerun"
        ) from exc
    if receipt is None or pack not in receipt["packs"]:
        raise PackClientError(
            f"pack-not-installed: Pack {pack!r} is not installed in {root}; "
            f"run `yoke packs list --project {project}` to see installed Packs"
        )
    _assert_checkout_receipt(root, receipt, project)
    _assert_no_dependents(project, pack, receipt, catalog, session_id=session_id)

    record = receipt["packs"][pack]
    updated = json.loads(json.dumps(receipt))
    del updated["packs"][pack]
    validate_receipt(updated)
    report: dict[str, Any] = {
        "operation": "remove",
        "project_id": receipt["project_id"],
        "project_slug": receipt["project_slug"],
        "repo_root": str(root),
        "pack": pack,
        "version": record["version"],
        "catalog": catalog.describe(),
        "drops": [
            f"{PACK_RECEIPT_REL} record for Pack {pack!r}",
            f"server install record for Pack {pack!r} in project "
            f"{receipt['project_slug']!r}",
        ],
        "kept_project_files": sorted(row["path"] for row in record["files"].values()),
        "remaining_packs": sorted(updated["packs"]),
        "applied": False,
        "receipt": str(root / PACK_RECEIPT_REL),
    }
    if not apply:
        return report

    # Report first: a failed report leaves the receipt untouched, so the same
    # command can be rerun. A failed receipt write after a good report is
    # also repaired by rerunning, which reports the same install list again.
    report["projection"] = _report_receipt(project, updated, session_id=session_id)
    try:
        write_receipt(root, updated)
    except OSError as exc:
        raise PackClientError(
            f"pack-receipt-write-failed: the server no longer lists Pack {pack!r} "
            f"but {PACK_RECEIPT_REL} could not be written ({exc}); fix the file "
            f"permissions and rerun `yoke packs remove {pack} --project {project} --apply`"
        ) from exc
    report["applied"] = True
    return report


def _assert_checkout_receipt(
    root: Path, receipt: Mapping[str, Any], project: str
) -> None:
    if project not in {receipt["project_slug"], str(receipt["project_id"])}:
        raise PackClientError(
            f"pack-project-mismatch: {PACK_RECEIPT_REL} belongs to project "
            f"{receipt['project_slug']!r}, not {project!r}; rerun with "
            f"--project {receipt['project_slug']}"
        )
    try:
        reference = existing_project_lookup.find_local_project_reference(
            root, config_path=None
        )
    except existing_project_lookup.ExistingProjectLookupError as exc:
        raise PackClientError(str(exc)) from exc
    if reference is None:
        raise PackClientError(
            "Pack operations require a checkout registered to a Yoke project"
        )
    if reference.project_id != receipt["project_id"]:
        raise PackClientError("Pack receipt belongs to a different project")


def _assert_no_dependents(
    project: str,
    pack: str,
    receipt: Mapping[str, Any],
    catalog: PackCatalog,
    *,
    session_id: str | None,
) -> None:
    dependents: list[str] = []
    for slug, record in sorted(receipt["packs"].items()):
        if slug == pack:
            continue
        try:
            bundle = _fetch_bundle(
                project,
                slug,
                version=record["version"],
                render_values=record["render_values"],
                session_id=session_id,
                catalog=catalog,
            )
        except PackClientError as exc:
            raise PackClientError(
                f"pack-dependencies-unknown: installed Pack {slug!r} "
                f"{record['version']} cannot be read from the {catalog.label()} "
                f"({exc}), so whether it depends on {pack!r} is unknown; rerun "
                f"with --catalog {catalog_spec(record['source'])}, or remove or "
                f"update Pack {slug!r} first"
            ) from exc
        if pack in bundle["dependencies"]:
            dependents.append(slug)
    if dependents:
        names = ", ".join(repr(slug) for slug in dependents)
        raise PackClientError(
            f"pack-required-by-installed: Pack {pack!r} is a dependency of "
            f"installed Pack(s) {names}; remove those first"
        )


__all__ = ["run_pack_remove"]
