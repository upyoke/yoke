"""Full-pipeline tests for yoke_core.domain.populate_registry.

Spins up a temporary git repo with a throwaway DB so the discovery pass can
walk the fake repo and populate a real registry without touching production.

Pure inference + parser tests live in test_populate_registry.py.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a minimal git repo with an isolated DB and mock scripts."""
    from yoke_core.domain import events_crud
    from runtime.api.fixtures.file_test_db import init_test_db

    scripts_dir = tmp_path / ".agents" / "skills" / "yoke" / "scripts"
    scripts_dir.mkdir(parents=True)

    api_dir = tmp_path / "runtime" / "api" / "domain"
    api_dir.mkdir(parents=True)

    docs_dir = tmp_path / "runtime" / "docs"
    docs_dir.mkdir(parents=True)

    # Mock call sites that discovery will pick up.
    (scripts_dir / "observe-tool.sh").write_text(
        '#!/usr/bin/env sh\n'
        'sh "$SCRIPT_DIR/emit-event.sh" --name "HarnessToolCallCompleted" --kind analytics --type tool_call --source-type agent\n'
        'sh "$SCRIPT_DIR/emit-event.sh" --name "HarnessToolCallFailed" --kind analytics --type tool_call --source-type agent\n'
    )
    (scripts_dir / "harness-session-start.sh").write_text(
        '#!/usr/bin/env sh\n'
        'sh "$SCRIPT_DIR/emit-event.sh" --name "SessionDiscoveryProbe" --kind system --type session --source-type system\n'
    )
    (scripts_dir / "shepherd-dispatch.sh").write_text(
        '#!/usr/bin/env sh\n'
        'sh "$SCRIPT_DIR/emit-event.sh" --name "ShepherdDispatched" --kind audit --type dispatch --source-type agent\n'
    )
    (scripts_dir / "health-check.sh").write_text(
        '#!/usr/bin/env sh\n'
        'sh "$SCRIPT_DIR/emit-event.sh" --name "HealthCheckPassed" --kind system --type health --source-type system\n'
        'sh "$SCRIPT_DIR/emit-event.sh" --name "AnomalyDetected" --kind system --type anomaly --source-type system\n'
    )
    (scripts_dir / "item-status.sh").write_text(
        '#!/usr/bin/env sh\n'
        'sh "$SCRIPT_DIR/emit-event.sh" --name "ItemStatusChanged" --kind audit --type status --source-type agent\n'
    )
    (scripts_dir / "deploy-pipeline.sh").write_text(
        '#!/usr/bin/env sh\n'
        'sh "$SCRIPT_DIR/emit-event.sh" --name "DeploymentStarted" --kind system --type deployment --source-type system\n'
        'sh "$SCRIPT_DIR/emit-event.sh" --name "DeploymentFailed" --kind system --type deployment --source-type system\n'
    )

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "test setup"],
        cwd=tmp_path,
        check=True,
    )

    with init_test_db(tmp_path / "runtime", apply_schema=events_crud.cmd_init) as db_path:
        monkeypatch.setenv("YOKE_DB", str(db_path))
        monkeypatch.setenv("YOKE_REPO_ROOT", str(tmp_path))
        yield tmp_path


def _run_populator(fake_repo: Path) -> str:
    """Invoke the populator against the fake repo and return summary."""
    from yoke_core.domain import populate_registry

    return populate_registry.populate_and_render(
        db_path=str(fake_repo / "runtime" / "yoke.db"),
        repo_root=str(fake_repo),
    )


def test_first_run_registers_discovered_events(fake_repo: Path):
    from yoke_core.domain import events_crud

    summary = _run_populator(fake_repo)

    assert re.search(r"\d+ total discovered", summary)
    assert re.search(r"\d+ newly registered", summary)
    assert re.search(r"\d+ already registered", summary)
    assert re.search(r"\d+ curated ensured", summary)
    assert re.search(r"\d+ deprecated", summary)
    assert not re.search(r"-\d+ already registered", summary)

    db_path = str(fake_repo / "runtime" / "yoke.db")
    for name in (
        "HarnessToolCallCompleted",
        "HarnessToolCallFailed",
        "HarnessSessionStarted",
        "AnomalyDetected",
        "ItemStatusChanged",
        "DeploymentFailed",
    ):
        row = events_crud.cmd_registry_get(db_path=db_path, name=name)
        assert name in row, f"{name} missing from registry"


def test_idempotent_second_run(fake_repo: Path):
    from yoke_core.domain import events_crud

    _run_populator(fake_repo)
    count_after_first = events_crud.cmd_registry_count(
        db_path=str(fake_repo / "runtime" / "yoke.db"),
        status="all",
    )

    summary2 = _run_populator(fake_repo)
    count_after_second = events_crud.cmd_registry_count(
        db_path=str(fake_repo / "runtime" / "yoke.db"),
        status="all",
    )

    assert count_after_first == count_after_second
    assert "0 newly registered" in summary2


def test_discovered_metadata_inference_matches_original_shell(fake_repo: Path):
    from yoke_core.domain import events_crud

    _run_populator(fake_repo)
    db = str(fake_repo / "runtime" / "yoke.db")

    shepherd_row = events_crud.cmd_registry_get(db_path=db, name="ShepherdDispatched")
    assert "shepherd-dispatch" in shepherd_row
    assert "audit" in shepherd_row

    session_row = events_crud.cmd_registry_get(db_path=db, name="SessionDiscoveryProbe")
    assert "harness-session-start" in session_row
    assert "system" in session_row
    assert "INFO" in session_row

    anomaly_row = events_crud.cmd_registry_get(db_path=db, name="AnomalyDetected")
    assert "WARN" in anomaly_row

    failed_row = events_crud.cmd_registry_get(db_path=db, name="DeploymentFailed")
    assert "WARN" in failed_row


def test_corrective_updates_override_inferred_metadata(fake_repo: Path):
    from yoke_core.domain import events_crud

    _run_populator(fake_repo)
    db = str(fake_repo / "runtime" / "yoke.db")

    row = events_crud.cmd_registry_get(db_path=db, name="ItemStatusChanged")
    assert "yoke_core.api.service_client" in row, row
    assert "lifecycle" in row
    assert "STATUS" in row

    tcc_row = events_crud.cmd_registry_get(db_path=db, name="HarnessToolCallCompleted")
    assert "yoke_core.domain.observe" in tcc_row


def test_curated_events_inserted_without_discovery(fake_repo: Path):
    """Curated events are registered even though the fake repo has no
    call sites for them."""
    from yoke_core.domain import events_crud

    _run_populator(fake_repo)
    db = str(fake_repo / "runtime" / "yoke.db")

    for name in ("QARunStarted", "FeedStarted", "DataLossDetected"):
        row = events_crud.cmd_registry_get(db_path=db, name=name)
        assert name in row, f"{name} missing from curated registrations"


def test_browser_daemon_startup_failed_registered_active(fake_repo: Path):
    from yoke_core.domain import events_crud

    _run_populator(fake_repo)
    db = str(fake_repo / "runtime" / "yoke.db")

    row = events_crud.cmd_registry_get(db_path=db, name="BrowserDaemonStartupFailed")
    assert "BrowserDaemonStartupFailed" in row
    assert "browser_daemon" in row
    assert "browser_qa" in row
    assert "ERROR" in row
    assert "deprecated" not in row


def test_deprecate_retired_events(fake_repo: Path):
    from yoke_core.domain import events_crud
    from yoke_core.domain.populate_registry import DEPRECATE_LIST

    db = str(fake_repo / "runtime" / "yoke.db")
    events_crud.cmd_init(db_path=db)
    for name in DEPRECATE_LIST:
        events_crud.cmd_registry_add(
            db_path=db,
            name=name,
            kind="system",
            event_type="legacy",
            service="legacy",
            description="seed for dep test",
            severity="INFO",
        )

    _run_populator(fake_repo)

    for name in DEPRECATE_LIST:
        row = events_crud.cmd_registry_get(db_path=db, name=name)
        assert "deprecated" in row, f"{name} was not deprecated"


def test_retire_mode_chosen(fake_repo: Path):
    from yoke_core.domain import events_crud

    db = str(fake_repo / "runtime" / "yoke.db")
    events_crud.cmd_init(db_path=db)
    events_crud.cmd_registry_add(
        db_path=db,
        name="ModeChosen",
        kind="workflow",
        event_type="retired",
        service="legacy",
        description="seed",
        severity="INFO",
    )

    _run_populator(fake_repo)

    row = events_crud.cmd_registry_get(db_path=db, name="ModeChosen")
    assert "retired" in row


def test_cleanup_test_sourced_entries(fake_repo: Path):
    """Entries whose description points at a tests/test-*.sh path with no
    production producer should get deprecated."""
    from yoke_core.domain import events_crud

    db = str(fake_repo / "runtime" / "yoke.db")
    events_crud.cmd_init(db_path=db)
    events_crud.cmd_registry_add(
        db_path=db,
        name="LegacyTestArtifact",
        kind="system",
        event_type="Unknown",
        service="test-populate-registry",
        description="Auto-discovered from .agents/skills/yoke/scripts/tests/test-populate-registry.sh",
        severity="INFO",
    )

    _run_populator(fake_repo)

    row = events_crud.cmd_registry_get(db_path=db, name="LegacyTestArtifact")
    assert "deprecated" in row


def test_cleanup_skips_entries_with_production_producers(fake_repo: Path):
    """Entries whose description references a test file should NOT be
    deprecated if the same event name appears in discovered production
    call sites."""
    from yoke_core.domain import events_crud

    db = str(fake_repo / "runtime" / "yoke.db")
    events_crud.cmd_init(db_path=db)
    events_crud.cmd_registry_add(
        db_path=db,
        name="HarnessToolCallCompleted",
        kind="system",
        event_type="Unknown",
        service="test-populate-registry",
        description="Auto-discovered from .agents/skills/yoke/scripts/tests/test-observe-tool.sh",
        severity="INFO",
    )

    _run_populator(fake_repo)

    row = events_crud.cmd_registry_get(db_path=db, name="HarnessToolCallCompleted")
    assert "deprecated" not in row, row


def test_catalog_rendered_with_expected_sections(fake_repo: Path):
    _run_populator(fake_repo)

    catalog = fake_repo / "docs" / "event-catalog.md"
    assert catalog.is_file(), "event-catalog.md was not created"
    body = catalog.read_text()

    assert "# Event Catalog" in body
    assert "python3 -m yoke_core.domain.populate_registry" in body
    assert "Event Name" in body
    assert "Kind" in body
    assert "Type" in body
    assert "Owner Service" in body
    assert "Severity" in body
    assert "Status" in body
    assert "HarnessToolCallCompleted" in body
    assert "HarnessSessionStarted" in body
    assert "AnomalyDetected" in body


def test_catalog_preserves_appendix_below_sentinel(fake_repo: Path):
    _run_populator(fake_repo)
    catalog = fake_repo / "docs" / "event-catalog.md"

    sentinel = "<!-- catalog-appendix-start -->"
    appendix = "\n## Hand-authored appendix\n\nEnvelope schema prose.\n"
    catalog.write_text(catalog.read_text() + "\n" + sentinel + appendix)

    _run_populator(fake_repo)

    body = catalog.read_text()
    assert sentinel in body
    assert "Hand-authored appendix" in body
    assert "Envelope schema prose." in body


def test_cli_entry_point(fake_repo: Path, capsys: pytest.CaptureFixture):
    from yoke_core.domain import populate_registry

    rc = populate_registry.main(
        [
            "--db",
            str(fake_repo / "runtime" / "yoke.db"),
            "--repo-root",
            str(fake_repo),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "total discovered" in captured.out
    assert "newly registered" in captured.out
