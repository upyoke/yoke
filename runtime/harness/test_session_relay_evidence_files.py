"""Machine-local listing and bounded tails behind one leased evidence job."""

from __future__ import annotations

import os
from pathlib import Path

from yoke_contracts.session_control.evidence_fetch import EVIDENCE_MAX_BYTES
from yoke_harness.session_relay_evidence_files import (
    ADAPTER_REVISION,
    list_session_evidence,
    read_session_evidence,
    read_tail,
)
from yoke_harness.session_relay_native_diagnostics import (
    diagnostic_reference,
    store_native_diagnostic,
)


SESSION_ID = "22222222-2222-4222-8222-222222222222"
#: The launch whose native produced the capture this session can read.
LAUNCH_ID = "33333333-3333-4333-8333-333333333333"


def _machine(tmp_path: Path) -> tuple[Path, Path]:
    """Lay out one machine's relay state dir and scratch root."""
    state_dir = tmp_path / "relay"
    state_dir.mkdir(mode=0o700)
    (state_dir / "relay.stderr.log").write_text(
        "relay boot\nrelay refused a wake\n", encoding="utf-8"
    )
    scratch_root = tmp_path / "scratch"
    captures = (
        scratch_root
        / "10"
        / "sessions"
        / SESSION_ID
        / "runs"
        / "pid-7"
        / ("watcher-captures")
    )
    captures.mkdir(parents=True)
    (captures / "yoke-pytest.raw.abc.log").write_text(
        "collecting\n1 failed\n", encoding="utf-8"
    )
    return state_dir, scratch_root


def test_listing_covers_every_kind_the_machine_holds(tmp_path: Path) -> None:
    state_dir, scratch_root = _machine(tmp_path)
    receipt = store_native_diagnostic(
        b"out",
        b"err",
        reference=diagnostic_reference(LAUNCH_ID),
        state_dir=state_dir,
    )

    found = list_session_evidence(
        SESSION_ID,
        kind=None,
        diagnostic_refs=[receipt.reference],
        state_dir=state_dir,
        scratch_root=scratch_root,
    )

    assert {entry.kind for entry in found} == {"relay", "watcher", "diagnostic"}
    # A watcher capture is named by its run so two runs never collide.
    assert any(entry.name == "pid-7/yoke-pytest.raw.abc.log" for entry in found)


def test_a_kind_narrows_the_listing(tmp_path: Path) -> None:
    state_dir, scratch_root = _machine(tmp_path)

    found = list_session_evidence(
        SESSION_ID,
        kind="watcher",
        state_dir=state_dir,
        scratch_root=scratch_root,
    )

    assert [entry.kind for entry in found] == ["watcher"]


def test_another_session_sees_none_of_these_captures(tmp_path: Path) -> None:
    state_dir, scratch_root = _machine(tmp_path)

    found = list_session_evidence(
        "77777777-7777-4777-8777-777777777777",
        kind="watcher",
        state_dir=state_dir,
        scratch_root=scratch_root,
    )

    assert found == []


def test_tail_returns_only_the_last_lines(tmp_path: Path) -> None:
    state_dir, scratch_root = _machine(tmp_path)
    entry = list_session_evidence(
        SESSION_ID, kind="relay", state_dir=state_dir, scratch_root=scratch_root
    )[0]

    content, truncated = read_tail(entry, tail_lines=1)

    assert content == "relay refused a wake"
    assert truncated is True


def test_one_enormous_line_is_capped_in_bytes(tmp_path: Path) -> None:
    state_dir, scratch_root = _machine(tmp_path)
    (state_dir / "relay.stdout.log").write_text("y" * 500_000, encoding="utf-8")
    entry = next(
        found
        for found in list_session_evidence(
            SESSION_ID, kind="relay", state_dir=state_dir, scratch_root=scratch_root
        )
        if found.name == "relay.stdout.log"
    )

    content, truncated = read_tail(entry, tail_lines=2000)

    assert len(content.encode("utf-8")) == EVIDENCE_MAX_BYTES
    assert truncated is True


def test_a_leased_job_reads_the_named_file(tmp_path: Path) -> None:
    state_dir, scratch_root = _machine(tmp_path)

    result = read_session_evidence(
        {
            "job_kind": "evidence",
            "target_session_id": SESSION_ID,
            "evidence_request": {
                "kind": "watcher",
                "file_name": "pid-7/yoke-pytest.raw.abc.log",
                "tail_lines": 5,
            },
        },
        state_dir=state_dir,
        scratch_root=scratch_root,
    )

    assert result.result_code == "read"
    assert result.adapter_revision == ADAPTER_REVISION
    assert result.document["selected_file"] == "pid-7/yoke-pytest.raw.abc.log"
    assert "1 failed" in result.document["content"]


def test_a_file_this_machine_does_not_hold_is_named_not_found(
    tmp_path: Path,
) -> None:
    state_dir, scratch_root = _machine(tmp_path)

    result = read_session_evidence(
        {
            "job_kind": "evidence",
            "target_session_id": SESSION_ID,
            "evidence_request": {"kind": "watcher", "file_name": "absent.log"},
        },
        state_dir=state_dir,
        scratch_root=scratch_root,
    )

    assert result.result_code == "not_found"
    # The listing still comes back, so the caller can pick a real file.
    assert result.document["files"]


def test_a_session_with_nothing_stored_reports_no_files(tmp_path: Path) -> None:
    state_dir = tmp_path / "relay"
    state_dir.mkdir(mode=0o700)

    result = read_session_evidence(
        {
            "job_kind": "evidence",
            "target_session_id": SESSION_ID,
            "evidence_request": {"kind": "watcher"},
        },
        state_dir=state_dir,
        scratch_root=tmp_path / "scratch",
    )

    assert result.result_code == "no_files"
    assert result.document == {"files": []}


def test_a_symlinked_capture_is_never_read(tmp_path: Path) -> None:
    state_dir, scratch_root = _machine(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    link = state_dir / "relay.stdout.log"
    os.symlink(secret, link)

    found = list_session_evidence(
        SESSION_ID, kind="relay", state_dir=state_dir, scratch_root=scratch_root
    )

    assert [entry.name for entry in found] == ["relay.stderr.log"]
