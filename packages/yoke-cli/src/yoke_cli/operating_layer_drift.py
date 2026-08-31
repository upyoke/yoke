"""Compare installed project teaching with the code handling its commands."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Union

from yoke_contracts.engine_version import (
    UNRESOLVED_SCM_FALLBACK_VERSION,
    compare_engine_versions,
)
from yoke_contracts.install_binding import source_checkout_root
from yoke_contracts.project_contract.installed_layer import (
    InstalledLayerReceipt,
    read_installed_layer_receipt,
)
from yoke_cli.transport import source_build_skew


RUNNING_AHEAD = "running_ahead"
RUNNING_BEHIND = "running_behind"
RUNNING_EQUAL = "running_equal"
RUNNING_DIVERGED = "running_diverged"
RUNNING_UNKNOWN = "running_unknown"


@dataclass(frozen=True)
class RunningReleaseComparison:
    """Relationship of the running code to one reference engine release."""

    relationship: str
    reference_release: str
    running_version: str = ""
    source_checkout: str = ""
    detail: str = ""


@dataclass(frozen=True)
class InstalledLayerComparison:
    """One installed-layer receipt compared with the running code."""

    receipt: InstalledLayerReceipt
    running: RunningReleaseComparison

    @property
    def layer_is_behind(self) -> bool:
        return self.running.relationship == RUNNING_AHEAD

    @property
    def running_is_behind(self) -> bool:
        return self.running.relationship == RUNNING_BEHIND


@lru_cache(maxsize=4)
def _current_source_layer_release(checkout_text: str) -> str:
    """Render source identity through the established subprocess boundary."""
    try:
        from yoke_cli.project_install.local_source import _build_bundle

        checkout = Path(checkout_text)
        bundle = _build_bundle(
            checkout,
            target_root=checkout,
            project_id=0,
            project_slug="identity-probe",
            apply=False,
        )
    except Exception:  # noqa: BLE001 - source identity is advisory only
        return ""
    return str(bundle.get("yoke_version") or "").strip()


def _source_comparison(
    checkout: Path,
    reference_release: str,
    reference_build: str,
) -> RunningReleaseComparison:
    source = source_build_skew.compare_to_server_build(
        str(checkout), reference_build,
    )
    source_relationship = source.relationship
    detail = source.reason
    if source_relationship == source_build_skew.EQUAL and reference_release.startswith(
        "source-"
    ):
        current_release = _current_source_layer_release(str(checkout))
        if not current_release:
            source_relationship = source_build_skew.UNKNOWN
            detail = "current source operating-layer identity is unavailable"
        elif current_release != reference_release:
            source_relationship = source_build_skew.AHEAD
            detail = "source operating-layer content changed at the same commit"
    relationship = {
        source_build_skew.AHEAD: RUNNING_AHEAD,
        source_build_skew.BEHIND: RUNNING_BEHIND,
        source_build_skew.EQUAL: RUNNING_EQUAL,
        source_build_skew.DIVERGED: RUNNING_DIVERGED,
    }.get(source_relationship, RUNNING_UNKNOWN)
    return RunningReleaseComparison(
        relationship,
        reference_release,
        source_checkout=str(checkout),
        detail=detail,
    )


def compare_running_to_release(
    reference_release: str,
    *,
    running_version: str,
    running_module_file: str,
    reference_source_build: str = "",
) -> RunningReleaseComparison:
    """Relate packaged or source-bound running code to *reference_release*."""
    reference = str(reference_release or "").strip()
    current = str(running_version or "").strip()
    source_build = str(reference_source_build or "").strip()
    if not reference:
        return RunningReleaseComparison(
            RUNNING_UNKNOWN, reference, running_version=current,
            detail="reference engine release is unavailable",
        )
    checkout = source_checkout_root(running_module_file)
    if checkout is not None and source_build:
        return _source_comparison(checkout, reference, source_build)
    if checkout is not None and reference.startswith("source-"):
        current_source_release = _current_source_layer_release(str(checkout))
        if not current_source_release:
            relationship = RUNNING_UNKNOWN
            detail = "current source operating-layer identity is unavailable"
        elif current_source_release == reference:
            relationship = RUNNING_EQUAL
            detail = ""
        else:
            relationship = RUNNING_AHEAD
            detail = "source operating-layer content differs from the legacy receipt"
        return RunningReleaseComparison(
            relationship,
            reference,
            running_version=current,
            source_checkout=str(checkout),
            detail=detail,
        )
    if (
        reference == UNRESOLVED_SCM_FALLBACK_VERSION
        or current == UNRESOLVED_SCM_FALLBACK_VERSION
    ):
        return RunningReleaseComparison(
            RUNNING_UNKNOWN,
            reference,
            running_version=current,
            detail="reference engine release is an unresolved source fallback",
        )
    if current:
        ordering = compare_engine_versions(current, reference)
        relationship = {
            -1: RUNNING_BEHIND,
            0: RUNNING_EQUAL,
            1: RUNNING_AHEAD,
        }.get(ordering, RUNNING_UNKNOWN)
        return RunningReleaseComparison(
            relationship,
            reference,
            running_version=current,
            detail=("engine versions are not comparable" if ordering is None else ""),
        )

    if checkout is None:
        return RunningReleaseComparison(
            RUNNING_UNKNOWN,
            reference,
            detail="running code has no package version or source checkout",
        )
    tag = reference if reference.startswith("v") else f"v{reference}"
    return _source_comparison(checkout, reference, tag)


def compare_installed_layer(
    start_path: Union[str, Path],
    *,
    running_version: str,
    running_module_file: str,
) -> InstalledLayerComparison | None:
    """Compare the nearest tracked operating-layer receipt with this code."""
    receipt = read_installed_layer_receipt(Path(start_path))
    if receipt is None:
        return None
    running = compare_running_to_release(
        receipt.source_engine_release,
        running_version=running_version,
        running_module_file=running_module_file,
        reference_source_build=receipt.source_build,
    )
    return InstalledLayerComparison(receipt, running)


def refresh_command(project_root: Path) -> str:
    """Exact project-layer refresh command for one checkout."""
    return f"yoke project install {shlex.quote(str(project_root))}"


def running_identity() -> tuple[str, str]:
    """This CLI's release version and module origin, the comparison inputs."""
    import yoke_cli
    from yoke_cli.config import install_binding

    return (
        install_binding.distribution_version(),
        str(yoke_cli.__file__ or ""),
    )


def stale_installed_layer(
    start_path: Union[str, Path],
) -> InstalledLayerComparison | None:
    """The nearest layer receipt, only when it is the established older side.

    ``None`` for no receipt, an equal or newer layer, and evidence too thin to
    order the two. Only a directional comparison may recommend replacing either
    side, because "reinstall something" is the advice that wastes an operator's
    afternoon when the stale component was the other one.
    """
    running_version, running_module_file = running_identity()
    installed = compare_installed_layer(
        Path(start_path),
        running_version=running_version,
        running_module_file=running_module_file,
    )
    if installed is None or not installed.layer_is_behind:
        return None
    return installed


def layer_refresh_advice(installed: InstalledLayerComparison) -> str:
    """Name the refresh, and name which side of the pair is the stale one."""
    command = refresh_command(installed.receipt.project_root)
    source_release = str(installed.receipt.source_engine_release or "")
    release_detail = (
        f" (generated by engine {source_release})" if source_release else ""
    )
    return (
        f"The installed project operating layer{release_detail} is older "
        "than the running CLI/source checkout. Refresh that layer with "
        f"`{command}`. Do not reinstall the newer CLI/source checkout; "
        "the project layer is the stale component."
    )


def installed_layer_recovery(start_path: Union[str, Path]) -> str:
    """The refresh advice for *start_path*, or ``""`` when none is warranted."""
    installed = stale_installed_layer(start_path)
    return layer_refresh_advice(installed) if installed is not None else ""


__all__ = [
    "InstalledLayerComparison",
    "RUNNING_AHEAD",
    "RUNNING_BEHIND",
    "RUNNING_DIVERGED",
    "RUNNING_EQUAL",
    "RUNNING_UNKNOWN",
    "RunningReleaseComparison",
    "compare_installed_layer",
    "compare_running_to_release",
    "installed_layer_recovery",
    "layer_refresh_advice",
    "refresh_command",
    "running_identity",
    "stale_installed_layer",
]
