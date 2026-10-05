"""Candidate matching preserves the scanner's exact line and path semantics."""

from __future__ import annotations

import re

import pytest

from yoke_project_checks import check_obsoleted_terms as scan


def test_candidates_preserve_labels_order_flags_and_line_boundaries(
    tmp_path, monkeypatch
):
    patterns = (
        r"\bretired\b",
        r"(?i)\bold\b",
        r"yoke_fake\.removed\b",
        r"^anchored$",
        r"retired\s+pair",
    )
    monkeypatch.setattr(scan, "OBSOLETED_TERM_PATTERNS", patterns)
    monkeypatch.setattr(
        scan, "OBSOLETED_TERM_LABELS", {p: str(i) for i, p in enumerate(patterns)}
    )
    monkeypatch.setattr(
        scan, "_PER_PATTERN_PATH_ALLOWLIST", {patterns[1]: ("docs/exempt",)}
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    texts = {
        "main.md": "retired OLD\r\nanchored\nyoke_fake/removed\nretired\npair\nretired pair\n",
        "exempt.md": "OLD retired\n",
        "empty.md": "",
    }
    for name, text in texts.items():
        (docs / name).write_bytes(text.encode())
    expected = []
    for path in scan._iter_scan_paths(tmp_path):
        rel = str(path.relative_to(tmp_path))
        for pattern in patterns:
            if scan._path_in_allowlist(
                rel, scan._PER_PATTERN_PATH_ALLOWLIST.get(pattern, ())
            ):
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                normalized = (
                    line.replace("/", ".")
                    if scan.needs_slash_normalization(pattern)
                    else line
                )
                if re.search(pattern, line) or re.search(pattern, normalized):
                    expected.append(
                        f"{rel}:{number}: [{scan.OBSOLETED_TERM_LABELS[pattern]}] {line}"
                    )
    assert scan.scan_repo(tmp_path) == expected


@pytest.mark.parametrize(
    "pattern,text",
    [
        (r"abc?", "ab"),
        (r"abc*", "ab"),
        (r"ab{0,2}", "a"),
        (r"abc|def", "def"),
        (r"abc(?:def|ghi)", "abcghi"),
        (r"abc[](|]|def", "def"),
        (r"abc(?#note)def|ghi", "ghi"),
        (r"(?i)indigo", "\u0131ndigo"),
        (r"(?x) a b", "ab"),
        (r"abc(?x: d e f )", "abcdef"),
        (r"^(ab)\1$", "abab"),
    ],
)
def test_prefix_filter_cannot_discard_a_valid_match(pattern, text):
    compiled = re.compile(pattern)
    assert compiled.search(text)
    prefix = scan._required_literal_prefix(compiled)
    assert not prefix or re.search(re.escape(prefix), text, compiled.flags)


def test_canonical_symlink_paths_keep_duplicate_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "OBSOLETED_TERM_PATTERNS", (r"retired",))
    monkeypatch.setattr(scan, "OBSOLETED_TERM_LABELS", {r"retired": "term"})
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "real.md").write_text("retired\n")
    (docs / "alias.md").symlink_to("real.md")
    assert scan.scan_repo(tmp_path) == ["docs/real.md:1: [term] retired"] * 2


def test_parallel_read_timeout_discards_partial_results(monkeypatch):
    import time
    from pathlib import Path

    from yoke_contracts import doctor_budget
    from yoke_core.engines.doctor_check_execution import execute_check_isolated
    from yoke_core.engines.doctor_registry_types import HealthCheck
    from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    monkeypatch.setattr(scan, "_iter_scan_paths", lambda root: [root / "slow"])

    def blocked(path):
        time.sleep(0.2)
        return path, ""

    monkeypatch.setattr(scan, "_read_scan_file", blocked)

    def check(conn, args, rec):
        rec.record("HC-partial", "Partial", "PASS", "")
        scan.scan_repo(Path("/tmp"))

    rec = RecordCollector()
    started = time.monotonic()
    execute_check_isolated(
        object(), DoctorArgs(), rec, HealthCheck("scan", "Scan", check)
    )
    assert time.monotonic() - started < 0.15
    assert [r.check_id for r in rec.results] == ["HC-check-incomplete"]


def test_complete_candidate_tree_finishes_within_doctor_budget():
    import time
    from pathlib import Path

    from yoke_contracts.doctor_budget import CHECK_BUDGET_S
    from yoke_core.engines.doctor_check_execution import execute_check_isolated
    from yoke_core.engines.doctor_registry_types import HealthCheck
    from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

    root = Path(__file__).resolve().parents[3]

    def check(conn, args, rec):
        hits = scan.scan_repo(root)
        rec.record(
            "HC-obsoleted-terms",
            "Complete candidate tree",
            "FAIL" if hits else "PASS",
            str(hits),
        )

    rec = RecordCollector()
    started = time.monotonic()
    execute_check_isolated(
        object(),
        DoctorArgs(),
        rec,
        HealthCheck("obsoleted-terms", "Complete candidate tree", check),
    )
    elapsed = time.monotonic() - started
    print(
        f"Complete candidate retired-term scan: {elapsed:.3f}s; budget {CHECK_BUDGET_S}s"
    )
    assert [(r.check_id, r.result) for r in rec.results] == [
        ("HC-obsoleted-terms", "PASS")
    ], rec.results
    assert elapsed < CHECK_BUDGET_S
