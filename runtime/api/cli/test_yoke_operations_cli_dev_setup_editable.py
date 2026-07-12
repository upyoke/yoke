"""Editable-install ordering coverage for ``yoke dev setup``."""

from __future__ import annotations

from pathlib import Path

from runtime.api.cli.test_yoke_operations_cli_dev_setup import _source_checkout
from yoke_cli.config import dev_setup


def test_dev_setup_editable_install_runs_last(tmp_path: Path, monkeypatch) -> None:
    # `uv pip install -e` repoints `yoke` by uninstalling the product wheel this
    # process runs from, so the editable install must be the LAST in-process
    # action — source-link and admin-config must both complete before it, never
    # after (running it mid-flow crashed the onboard wizard the same way).
    checkout = _source_checkout(tmp_path)
    order: list[object] = []

    monkeypatch.setattr(
        dev_setup, "_resolve_dsn",
        lambda *a, **k: (
            "secret-dsn",
            {"kind": "dsn_file", "path": str(tmp_path / "secret.dsn")},
        ),
    )
    monkeypatch.setattr(
        dev_setup, "install_source_checkout",
        lambda root, *, editable_install: order.append(
            ("source_link", editable_install)
        ) or {
            "source_link": {"mode": "source-link"},
            "machine_config_newly_registered": False,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        dev_setup, "_configure_admin_connection",
        lambda **kw: order.append("config") or {"connection": {}},
    )
    monkeypatch.setattr(
        dev_setup, "run_editable_install_step",
        lambda root: order.append("editable") or {"ok": True, "editable_install": {}},
    )

    report = dev_setup.build_report(
        checkout=str(checkout),
        config_path=str(tmp_path / "config.json"),
        env_name="source-dev-admin",
        dsn="postgresql://admin@localhost/yoke",
        apply=True,
        set_active_env=False,
        editable_install=True,
    )

    # source-link is invoked decoupled (editable_install=False), admin-config
    # runs in-process, and the editable install runs strictly last.
    assert order == [("source_link", False), "config", "editable"]
    assert report["editable_install"] == {"ok": True, "editable_install": {}}


def test_dev_setup_editable_install_failure_is_reported_not_raised(
    tmp_path: Path, monkeypatch
) -> None:
    # A failed editable install must surface in the report (ok=False) rather
    # than raising — it is the last step, so the already-applied source-link and
    # config stay intact and the operator gets a clear recovery hint.
    checkout = _source_checkout(tmp_path)
    monkeypatch.setattr(
        dev_setup, "_resolve_dsn", lambda *a, **k: (None, None),
    )
    monkeypatch.setattr(
        dev_setup, "install_source_checkout",
        lambda root, *, editable_install: {
            "source_link": {"mode": "source-link"},
            "machine_config_newly_registered": False,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        dev_setup, "run_editable_install_step",
        lambda root: {"ok": False, "error": "editable install failed: no uv"},
    )

    report = dev_setup.build_report(
        checkout=str(checkout),
        config_path=str(tmp_path / "config.json"),
        env_name="source-dev-admin",
        apply=True,
        set_active_env=False,
        editable_install=True,
    )

    assert report["applied"] is True
    assert report["editable_install"] == {
        "ok": False, "error": "editable install failed: no uv",
    }
    human = dev_setup.render_human(report)
    assert "editable install: FAILED" in human
    assert "--editable-install --yes" in human
