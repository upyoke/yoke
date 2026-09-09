"""A relayed registration denial carries the client-only mapping diagnosis.

The server sees an absent project id and says the checkout has none; only
this machine's config knows the checkout is registered under a different
connection env. These cover the client attaching that fact to the denial
it prints, and staying silent when there is nothing true to add.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import machine_config_writer
from yoke_harness.hooks.checkout_env_relay_notice import (
    annotate_checkout_env_mismatch,
    checkout_env_mismatch_notice,
)

DENIAL = (
    "Yoke hook registration denied: this checkout has no configured "
    "project id. Run Yoke setup for this checkout.\n"
)


@pytest.fixture()
def mapped_elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout registered under ``local`` while ``upyoke`` is selected."""
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    cfg = home / "config.json"
    for env in ("local", "upyoke"):
        dsn = tmp_path / f"{env}.dsn"
        dsn.write_text(f"postgresql://localhost/{env}\n", encoding="utf-8")
        machine_config_writer.set_connection(
            env, transport="local-postgres", dsn_file=str(dsn), path=cfg,
        )
    machine_config_writer.set_active_env("local", path=cfg)
    checkout = tmp_path / "mini"
    checkout.mkdir()
    machine_config_writer.register_project(checkout, 4, path=cfg)
    monkeypatch.setenv("YOKE_ENV", "upyoke")
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(cfg))
    return checkout


def test_denial_without_a_project_id_gains_the_mapping_diagnosis(
    mapped_elsewhere: Path,
) -> None:
    annotated = annotate_checkout_env_mismatch(
        DENIAL, {"cwd": str(mapped_elsewhere)}, None,
    )

    assert DENIAL.strip() in annotated
    assert "project 4 on env local" in annotated
    assert "the selected env is upyoke" in annotated


def test_a_denial_that_carried_a_project_id_is_left_alone(
    mapped_elsewhere: Path,
) -> None:
    assert (
        annotate_checkout_env_mismatch(DENIAL, {"cwd": str(mapped_elsewhere)}, 4)
        == DENIAL
    )


def test_an_unmapped_checkout_adds_nothing(tmp_path: Path) -> None:
    assert checkout_env_mismatch_notice({"cwd": str(tmp_path)}) == ""
    assert annotate_checkout_env_mismatch(DENIAL, {"cwd": str(tmp_path)}, None) == DENIAL


def test_a_deny_envelope_keeps_its_shape(mapped_elsewhere: Path) -> None:
    envelope = json.dumps({
        "hookSpecificOutput": {
            "permissionDecision": "deny",
            "permissionDecisionReason": DENIAL.strip(),
        }
    })

    annotated = json.loads(
        annotate_checkout_env_mismatch(
            envelope, {"cwd": str(mapped_elsewhere)}, None,
        )
    )
    reason = annotated["hookSpecificOutput"]["permissionDecisionReason"]

    assert annotated["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "project 4 on env local" in reason


def test_the_diagnosis_is_added_once(mapped_elsewhere: Path) -> None:
    once = annotate_checkout_env_mismatch(DENIAL, {"cwd": str(mapped_elsewhere)}, None)
    twice = annotate_checkout_env_mismatch(
        once, {"cwd": str(mapped_elsewhere)}, None,
    )

    assert once == twice
