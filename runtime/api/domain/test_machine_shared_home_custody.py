"""Golden custody follows the host and user a Test Machine resets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.domain.machine_operation_test_support import (
    ACTOR,
    MACHINE,
    begin_operation,
    run_operation,
)
from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import (
    GOLDEN_BASELINE_PATH,
    FakeHostControl,
    make_conn,
)
from yoke_contracts.machine_config.test_machine import validate_test_machine_settings
from yoke_core.domain.coordination_claims import acquire
from yoke_core.domain.machine_qa_capability import host_claim_target

OTHER_GOLDEN = "/Users/Shared/yoke-golden/yoke-test-home-platform"


def _settings(**overrides: str) -> str:
    return json.dumps(
        validate_test_machine_settings({**TEST_MACHINE_SETTINGS, **overrides}),
        separators=(",", ":"),
        sort_keys=True,
    )


def _machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    conn.execute(
        "UPDATE project_capabilities SET settings=? WHERE type LIKE 'test-machine:%'",
        (_settings(golden_baseline_path=GOLDEN_BASELINE_PATH),),
    )
    conn.execute(
        "INSERT INTO projects(id,slug,name,public_item_prefix) "
        "VALUES(2,'platform','Platform','PLAT')"
    )
    conn.commit()
    return conn


def _register_platform(conn, name: str, settings: str) -> None:
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "VALUES(2,?,?,'2026-08-02T00:00:00Z')",
        (f"test-machine:{name}", settings),
    )
    conn.commit()


def test_a_differently_named_registration_of_the_same_home_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _machine(tmp_path, monkeypatch)
    _register_platform(
        conn,
        "platform-mac",
        _settings(
            resource_name="platform-mac",
            host=TEST_MACHINE_SETTINGS["host"].upper(),
            golden_baseline_path=OTHER_GOLDEN,
        ),
    )

    submitted, execution = run_operation("golden_capture", control=FakeHostControl())

    assert submitted.primary_success, submitted.error
    kept = submitted.result_payload["kept_golden_paths"]
    assert kept == sorted({execution["golden_destination"], OTHER_GOLDEN})


@pytest.mark.parametrize(
    "overrides",
    [{"host": "other-mac.local"}, {"user": "someone-else"}],
    ids=["other-host", "other-user"],
)
def test_the_same_name_on_another_home_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str]
) -> None:
    conn = _machine(tmp_path, monkeypatch)
    _register_platform(
        conn, MACHINE, _settings(golden_baseline_path=OTHER_GOLDEN, **overrides)
    )

    submitted, execution = run_operation("golden_capture", control=FakeHostControl())

    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["kept_golden_paths"] == [
        execution["golden_destination"]
    ]


def test_a_leased_other_name_for_the_same_home_keeps_every_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _machine(tmp_path, monkeypatch)
    _register_platform(
        conn,
        "platform-mac",
        _settings(resource_name="platform-mac", golden_baseline_path=OTHER_GOLDEN),
    )
    acquire(conn, host_claim_target("platform-mac"), ACTOR.session_id)

    submitted, _execution = run_operation("golden_capture", control=FakeHostControl())

    assert submitted.primary_success, submitted.error
    assert "kept_golden_paths" not in submitted.result_payload
    assert submitted.result_payload["kept_golden_paths_unknown"]


def test_an_unreadable_registration_makes_the_kept_goldens_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _machine(tmp_path, monkeypatch)
    _register_platform(conn, "platform-mac", "{not json")

    submitted, _execution = run_operation("golden_capture", control=FakeHostControl())

    assert submitted.primary_success, submitted.error
    assert "kept_golden_paths" not in submitted.result_payload
    assert submitted.result_payload["kept_golden_paths_unknown"]


def test_verify_begin_names_every_golden_registered_for_this_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _machine(tmp_path, monkeypatch)
    _register_platform(
        conn,
        "platform-mac",
        _settings(resource_name="platform-mac", golden_baseline_path=OTHER_GOLDEN),
    )
    _register_platform(
        conn,
        "elsewhere",
        _settings(
            resource_name="elsewhere",
            host="other-mac.local",
            golden_baseline_path="/Users/Shared/yoke-golden/elsewhere",
        ),
    )

    begun = begin_operation("verify", control=FakeHostControl())

    assert begun.primary_success, begun.error
    assert begun.result_payload["registered_goldens"] == [
        {"project": "yoke", "test_machine": MACHINE, "path": GOLDEN_BASELINE_PATH},
        {"project": "platform", "test_machine": "platform-mac", "path": OTHER_GOLDEN},
    ]


def test_only_verify_begin_names_registered_goldens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _machine(tmp_path, monkeypatch)

    begun = begin_operation("screenshot", control=FakeHostControl())

    assert begun.primary_success, begun.error
    assert "registered_goldens" not in begun.result_payload
