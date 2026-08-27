"""Doctor coverage for leaked per-environment machine-relay login items."""

from __future__ import annotations

from pathlib import Path
import plistlib

import pytest

from yoke_cli.config import machine_config
from yoke_cli.config.session_relay_instance import PROD_RELAY_LABEL
from yoke_core.engines import doctor_hc_session_relay_orphans as orphans_hc
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.tools import launchctl_boundary as boundary


def _write(agents: Path, label: str, config_path: Path | None) -> Path:
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / f"{label}.plist"
    document: dict[str, object] = {"Label": label}
    if config_path is not None:
        document["EnvironmentVariables"] = {
            machine_config.CONFIG_FILE_ENV: str(config_path)
        }
    path.write_bytes(plistlib.dumps(document))
    return path


def test_only_a_relay_whose_machine_config_is_gone_counts_as_an_orphan(
    tmp_path: Path,
) -> None:
    agents = tmp_path / "LaunchAgents"
    live_config = tmp_path / "home" / "config.json"
    live_config.parent.mkdir(parents=True)
    live_config.write_text("{}", encoding="utf-8")
    _write(agents, f"{PROD_RELAY_LABEL}.aaaaaaaa", live_config)
    _write(agents, f"{PROD_RELAY_LABEL}.bbbbbbbb", tmp_path / "gone" / "config.json")
    _write(agents, PROD_RELAY_LABEL, None)

    found, unreadable = orphans_hc.scan_relay_login_items(agents)

    assert [orphan.label for orphan in found] == [f"{PROD_RELAY_LABEL}.bbbbbbbb"]
    assert unreadable == []


def test_the_canonical_relay_is_never_a_candidate_even_under_a_suffixed_name(
    tmp_path: Path,
) -> None:
    agents = tmp_path / "LaunchAgents"
    path = _write(agents, f"{PROD_RELAY_LABEL}.cccccccc", tmp_path / "gone.json")
    path.write_bytes(plistlib.dumps({"Label": PROD_RELAY_LABEL}))

    found, _ = orphans_hc.scan_relay_login_items(agents)

    assert found == []


def test_an_unreadable_plist_is_reported_and_left_in_place(tmp_path: Path) -> None:
    agents = tmp_path / "LaunchAgents"
    agents.mkdir(parents=True)
    corrupt = agents / f"{PROD_RELAY_LABEL}.dddddddd.plist"
    corrupt.write_bytes(b"not a plist")

    found, unreadable = orphans_hc.scan_relay_login_items(agents)

    assert found == []
    assert unreadable == [corrupt]
    assert corrupt.is_file()


def test_fix_unloads_and_deletes_exactly_the_orphans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = tmp_path / "launchd-sandbox"
    monkeypatch.setenv(boundary.SANDBOX_ENV, str(sandbox))
    agents = tmp_path / "LaunchAgents"
    live_config = tmp_path / "config.json"
    live_config.write_text("{}", encoding="utf-8")
    kept = _write(agents, f"{PROD_RELAY_LABEL}.eeeeeeee", live_config)
    orphan = _write(agents, f"{PROD_RELAY_LABEL}.ffffffff", tmp_path / "gone.json")
    monkeypatch.setattr(orphans_hc.sys, "platform", "darwin")
    monkeypatch.setattr(orphans_hc, "launch_agents_dir", lambda *_a, **_k: agents)
    rec = RecordCollector()

    orphans_hc.hc_session_relay_orphans(None, DoctorArgs(fix=True), rec)

    assert rec.results[0].result == "PASS"
    assert not orphan.exists()
    assert kept.is_file()
    assert [entry[1] for entry in boundary.recorded_commands(sandbox)] == ["bootout"]
    assert boundary.recorded_commands(sandbox)[0][-1].endswith(
        f"{PROD_RELAY_LABEL}.ffffffff"
    )


def test_a_detect_only_run_fails_and_teaches_the_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = tmp_path / "LaunchAgents"
    _write(agents, f"{PROD_RELAY_LABEL}.99999999", tmp_path / "gone.json")
    monkeypatch.setattr(orphans_hc.sys, "platform", "darwin")
    monkeypatch.setattr(orphans_hc, "launch_agents_dir", lambda *_a, **_k: agents)
    rec = RecordCollector()

    orphans_hc.hc_session_relay_orphans(None, DoctorArgs(), rec)

    detail = rec.results[0].detail
    assert rec.results[0].result == "FAIL"
    assert "yoke doctor run --quick --fix" in detail
    assert f"{PROD_RELAY_LABEL}.99999999" in detail
    assert "sfltool resetbtm" in detail


def test_the_check_is_not_applicable_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orphans_hc.sys, "platform", "linux")
    rec = RecordCollector()

    orphans_hc.hc_session_relay_orphans(None, DoctorArgs(), rec)

    assert rec.results[0].result == orphans_hc.NOT_APPLICABLE
