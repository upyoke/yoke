"""Unit tests for HC-tier-module-path-resolution.

Monkeypatches ``iter_tier_paths`` + ``_resolve_repo_root`` so the suite
is self-contained. Module resolution runs against the live interpreter
(importlib's spec cache makes it fast + deterministic).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple

import pytest

from yoke_core.engines import doctor_hc_tier_module_path_resolution as mod
from yoke_core.engines.doctor_hc_tier_module_path_resolution import (
    HC_SLUG,
    hc_tier_module_path_resolution,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


# Tier-anchored relative paths reused by the sibling tier-discipline tests.
_AGENTS = "AGENTS.md"
_OVERVIEW = "docs/OVERVIEW.md"
_ENGINEER_AGENT = "runtime/agents/engineer.md"
_CONDUCT_SKILL = ".agents/skills/yoke/conduct/SKILL.md"

_REAL_MODULE = "yoke_contracts.api.function_call"
_BOGUS_MODULE = "yoke_core.domain.yoke_function_envelope"  # YOK-1700 incident


@pytest.fixture
def conn():
    """The HC under test resolves module paths only; it never reads *conn*."""
    return None


def _materialize(tmp_path: Path, files: Dict[str, str]) -> Path:
    for rel, content in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def _setup(tmp_path, monkeypatch, files, tier_for):
    _materialize(tmp_path, files)

    def fake_iter(
        repo: Path, tiers: Iterable[int] = (0, 2, 4, 5)
    ) -> Iterator[Tuple[int, Path]]:
        tier_set = set(tiers)
        for rel, tier in sorted(tier_for.items()):
            if tier in tier_set:
                yield tier, tmp_path / rel

    monkeypatch.setattr(mod, "iter_tier_paths", fake_iter)
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(tmp_path))


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_tier_module_path_resolution(conn, DoctorArgs(), rec)
    return rec


def _detail(rec: RecordCollector) -> str:
    return rec.results[0].detail


@pytest.mark.parametrize(
    "body, expected_substr",
    [
        # Canonical incident: confabulated envelope module.
        (
            f"Use `{_BOGUS_MODULE}` to wrap calls.\n",
            _BOGUS_MODULE,
        ),
        # Sub-symbol on a real module that doesn't export the leaf.
        (
            f"Build a `{_REAL_MODULE}.NonexistentClass` envelope.\n",
            f"{_REAL_MODULE}.NonexistentClass",
        ),
        # Confabulated path inside a ``python`` fence still fires.
        (
            f"```python\nfrom {_BOGUS_MODULE} import Foo\n```\n",
            _BOGUS_MODULE,
        ),
    ],
    ids=["envelope-confab", "missing-sub-symbol", "inside-python-fence"],
)
def test_unresolved_citations_fire(
    tmp_path, monkeypatch, conn, body, expected_substr
):
    """Each unresolved-module shape produces a WARN naming the dotted path."""

    _setup(tmp_path, monkeypatch, {_OVERVIEW: body}, {_OVERVIEW: 2})
    rec = _run(conn)
    assert rec.results[0].result == "WARN"
    assert rec.results[0].check_id == HC_SLUG
    detail = _detail(rec)
    assert "unresolved module path" in detail
    assert expected_substr in detail


# Negative cases: real modules + fenced output + placeholder shapes.
# Real-package + wildcard/single-letter shapes are simply not matched
# by the regex; the placeholder leaf filter catches the rest. Empty
# file is a trivial input. All entries default to tier 2 / _OVERVIEW
# unless they need a different tier to exercise iter_tier_paths.
_PASS_CASES = [
    ("real-module", f"See `{_REAL_MODULE}` for the schema.\n", _AGENTS, 0),
    (
        "real-sub-symbol",
        f"Build a `{_REAL_MODULE}.FunctionCallRequest` and dispatch.\n",
        _ENGINEER_AGENT,
        4,
    ),
    (
        "real-package-no-leaf",
        "See `yoke_core.engines.doctor` for the engine.\n",
        _CONDUCT_SKILL,
        5,
    ),
    ("empty-file", "", _AGENTS, 0),
    ("text-fence", f"Example:\n```text\n{_BOGUS_MODULE}\n```\n", _OVERVIEW, 2),
    (
        "diff-fence",
        f"```diff\n-from {_BOGUS_MODULE} import X\n+from {_REAL_MODULE} import X\n```\n",
        _OVERVIEW,
        2,
    ),
    ("foo-leaf", "Generic: `yoke_core.domain.foo`.\n", _OVERVIEW, 2),
    ("foo-bar-pair", "Pair: `yoke_core.domain.foo.bar`.\n", _OVERVIEW, 2),
    ("other-module-leaf", "Schematic: `yoke_core.domain.other_module`.\n", _OVERVIEW, 2),
    ("single-letter-X", "Placeholder: `yoke_core.board.X`.\n", _OVERVIEW, 2),
    ("wildcard-suffix", "Wildcard: `yoke_core.tools.watch_*`.\n", _OVERVIEW, 2),
]


@pytest.mark.parametrize(
    "body, rel, tier",
    [case[1:] for case in _PASS_CASES],
    ids=[case[0] for case in _PASS_CASES],
)
def test_resolvable_or_exempt_citations_pass(
    tmp_path, monkeypatch, conn, body, rel, tier
):
    """Real modules, fenced output, and placeholder shapes all PASS."""

    _setup(tmp_path, monkeypatch, {rel: body}, {rel: tier})
    assert _run(conn).results[0].result == "PASS"


def test_archive_path_does_not_fire(tmp_path, monkeypatch, conn):
    """Files under ``docs/archive/`` are exempt by default (NFR-5)."""

    rel = "docs/archive/decisions/legacy.md"
    body = f"Old prose cited `{_BOGUS_MODULE}`.\n"
    _materialize(tmp_path, {rel: body})
    monkeypatch.setattr(
        mod,
        "iter_tier_paths",
        lambda repo, tiers=(0, 2, 4, 5): iter([(6, repo / rel)]),
    )
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(tmp_path))

    assert _run(conn).results[0].result == "PASS"


def test_self_skips_when_repo_root_unresolvable(monkeypatch, conn):
    """Falsy ``_resolve_repo_root`` → PASS with "skip" detail."""

    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: None)
    rec = _run(conn)
    assert rec.results[0].result == "PASS"
    assert "skip" in rec.results[0].detail.lower()


def test_consumes_upstream_constants_from_task_001():
    """HC consumes TIER_GLOBS + iter_tier_paths + archive prefixes."""

    from yoke_core.engines import doctor_registry_tier_discipline as up

    assert mod.TIER_GLOBS is up.TIER_GLOBS
    assert mod.iter_tier_paths is up.iter_tier_paths
    assert mod.TIER_6_ARCHIVE_PREFIXES is up.TIER_6_ARCHIVE_PREFIXES


def test_finding_label_matches_ac_2():
    """HC slug and label match the AC-2 contract."""

    assert HC_SLUG == "HC-tier-module-path-resolution"
    assert mod.HC_LABEL == (
        "Tier 0/2/4/5 surface cites a runtime.api.* module that does not resolve"
    )


def test_truncation_to_max_findings(tmp_path, monkeypatch, conn):
    """Output truncates at ``_MAX_FINDINGS`` with an overflow marker."""

    lines = [
        f"line {i}: cites `{_BOGUS_MODULE}_{i:02d}`"
        for i in range(mod._MAX_FINDINGS + 5)
    ]
    _setup(
        tmp_path,
        monkeypatch,
        {_OVERVIEW: "\n".join(lines) + "\n"},
        {_OVERVIEW: 2},
    )
    assert "more findings" in _detail(_run(conn))
