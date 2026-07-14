"""Install bundles report the serving engine distribution's version."""

from __future__ import annotations

from yoke_contracts.engine_version import UNRESOLVED_SCM_FALLBACK_VERSION
from yoke_core.domain import install_bundle


def test_bundle_version_uses_engine_distribution_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        install_bundle,
        "installed_engine_version",
        lambda: "0.1.1+launch.24",
    )

    assert install_bundle.yoke_version() == "0.1.1+launch.24"


def test_bundle_version_uses_shared_source_fallback(monkeypatch) -> None:
    monkeypatch.setattr(install_bundle, "installed_engine_version", lambda: "")

    assert install_bundle.yoke_version() == UNRESOLVED_SCM_FALLBACK_VERSION
