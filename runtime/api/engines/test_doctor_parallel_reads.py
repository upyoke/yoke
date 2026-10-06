"""Parallel Doctor reads preserve ordering and share the parent's deadline."""

import time

import pytest

from yoke_contracts import doctor_budget
from yoke_core.engines.doctor_parallel_reads import bounded_read_map


def test_reads_keep_input_order_and_inherit_remaining_budget(monkeypatch):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.1)

    def read(value):
        time.sleep(0.002 * (4 - value))
        return value, doctor_budget.remaining_seconds(100)

    with doctor_budget.check_budget():
        rows = list(bounded_read_map(read, range(4)))
    assert [value for value, _ in rows] == list(range(4))
    assert all(0 < remaining <= 0.1 for _, remaining in rows)


def test_read_deadline_does_not_wait_for_other_pending_reads(monkeypatch):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    started = time.monotonic()
    with (
        pytest.raises(doctor_budget.DoctorBudgetExhausted),
        doctor_budget.check_budget(),
    ):
        list(bounded_read_map(lambda _: time.sleep(0.2), range(20)))
    assert time.monotonic() - started < 0.15


def test_prefetched_reader_preserves_decode_failure_and_reads_once(tmp_path):
    import pytest
    from yoke_core.engines.doctor_parallel_reads import prefetched_text_reader

    source = tmp_path / "source.py"
    invalid = tmp_path / "invalid.py"
    source.write_text("before")
    invalid.write_bytes(b"\xff")
    reader = prefetched_text_reader([source, source, invalid])
    source.write_text("after")
    assert reader(source, encoding="utf-8") == "before"
    with pytest.raises(UnicodeDecodeError):
        reader(invalid, encoding="utf-8")


def test_parallel_inventory_preserves_serial_classifications_and_counts(tmp_path):
    import subprocess
    from yoke_core.domain.file_line_check import inventory

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "source.py").write_text("first\nsecond\n")
    (tmp_path / "binary.dat").write_bytes(b"\xff")
    (tmp_path / "alias.py").symlink_to("source.py")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    assert inventory(repo_root=tmp_path, read_map=bounded_read_map) == inventory(
        repo_root=tmp_path
    )


def test_prefetched_text_preserves_all_item_reference_scans(tmp_path):
    from yoke_core.domain import lint_item_ref_construction as refs
    from yoke_core.domain import lint_item_ref_message_text as messages
    from yoke_core.domain.lint_item_ref_bare_cli_token import (
        scan_bare_internal_cli_token,
    )
    from yoke_core.engines.doctor_parallel_reads import prefetched_text_reader

    source = tmp_path / "packages" / "consumer.py"
    source.parent.mkdir()
    source.write_text('value = f"YOK-{item_id}"\nmessage = f"item {item_id}"\n')
    reader = prefetched_text_reader([source])
    assert refs.scan(tmp_path, ["YOK"], read_text=reader) == refs.scan(
        tmp_path, ["YOK"]
    )
    for scan in (
        refs.scan_parser_policy,
        refs.stale_parser_policy_allowances,
        scan_bare_internal_cli_token,
        messages.scan_message_text_item_ids,
        messages.scan_display_ref_search_keys,
    ):
        assert scan(tmp_path, read_text=reader) == scan(tmp_path)
