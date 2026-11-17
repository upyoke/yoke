"""Shrink-only known-failure baselines for the Windows and macOS suite runs.

Linux CI owns the full suite's verdict. The on-demand ``yoke-suite`` workflow
runs the same suite on Windows and macOS, where some tests do not pass yet.
Each such test is listed, with the reason, in a JSON file under
``runtime/known_failure_baselines/<os>/`` and expected to fail on that OS only:

- a listed test is marked ``xfail(strict=True)``; a failure in its setup,
  call or teardown is reported as xfailed;
- a listed test that now passes fails the run as XPASS(strict), so the entry
  must be deleted in the same change (the baseline only shrinks);
- a listed test module (an entry without ``::``) is one that cannot be
  imported on that OS; its collection error is reported as skipped. Once it
  imports, every test in it is a listed test, so each one that passes fails
  the run until the entry is deleted;
- an unlisted failure fails the run as usual.

A test that fails in some runs and passes in others cannot be held by a
strict entry. It goes in ``runtime/known_failure_baselines/flaky/<os>.json``
instead, as ``{"<node id>": {"reason": ..., "feedback": <entry id>, "fix_item": "YOK-N"}}``,
naming the feedback entry that records it and the item that fixes it; the
entry is deleted when that fix lands. A flaky test is marked
``xfail(strict=False)``: its failures never fail the run, and its passes do
not either. Keep that list by hand; the recorder never writes it.

Entries are pytest node ids relative to the repository root, always written
with ``/`` separators. A parametrized node id names one case; a node id
without parameters covers every case of that test.

Only runs that set ``YOKE_KNOWN_FAILURE_BASELINE=1`` (the workflow does) apply
a baseline. A developer's own Mac is not the CI runner image: a test the
runner fails may pass there, and a local run judges every test plainly.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

#: Set to ``1`` by the yoke-suite workflow to apply this OS's baseline.
ENABLE_ENV = "YOKE_KNOWN_FAILURE_BASELINE"

BASELINE_DIR = Path(__file__).resolve().parent / "known_failure_baselines"

#: The baseline each ``sys.platform`` reads; Linux has none.
PLATFORM_BASELINES = {"win32": "windows", "darwin": "macos"}

FLAKY_DIR = BASELINE_DIR / "flaky"

_ENTRIES = pytest.StashKey[dict]()
_FLAKY = pytest.StashKey[dict]()
_FLAKY_REASON = pytest.StashKey[str]()
_REASON = pytest.StashKey[str]()
_PASSED_SO_FAR = pytest.StashKey[bool]()

#: The message a listed test that passed every phase fails with.
XPASS_MARK = "[XPASS(strict)]"


def baseline_files(os_name: str) -> list[Path]:
    return sorted((BASELINE_DIR / os_name).glob("*.json"))


def load_baseline(os_name: str) -> dict[str, str]:
    """The ``{node id: reason}`` baseline for *os_name*, merged across its files."""
    entries: dict[str, str] = {}
    for path in baseline_files(os_name):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise pytest.UsageError(
                f"known_failure_baseline_unreadable: {path} ({exc}); restore it as a "
                "JSON object mapping pytest node ids to reasons"
            ) from exc
        if not isinstance(loaded, dict):
            raise pytest.UsageError(
                f"known_failure_baseline_invalid: {path} must be a JSON object "
                "mapping pytest node ids to reasons"
            )
        repeated = sorted(entries.keys() & loaded.keys())
        if repeated:
            raise pytest.UsageError(
                f"known_failure_baseline_duplicate: {path} repeats {repeated[0]}; "
                "keep each node id in one file"
            )
        entries.update(loaded)
    return entries


def load_flaky(os_name: str) -> dict[str, dict]:
    """The ``{node id: {"reason", "feedback"}}`` flaky list for *os_name*."""
    path = FLAKY_DIR / f"{os_name}.json"
    if not path.is_file():
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise pytest.UsageError(f"known_flaky_list_unreadable: {path} ({exc}); restore its JSON") from exc
    for node_id, entry in (entries.items() if isinstance(entries, dict) else [(None, None)]):
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("reason"), str) and entry["reason"].strip()
            and isinstance(entry.get("feedback"), int)
            and re.fullmatch(r"[A-Z]+-\d+", str(entry.get("fix_item", "")))
        ):
            raise pytest.UsageError(
                f"known_flaky_list_invalid: {path} entry {node_id!r} needs a reason, the "
                "integer id of the feedback entry that records it, and its fix item (PREFIX-N)"
            )
    return entries


def baseline_reason(node_id: str, entries: dict[str, str]) -> str | None:
    """The reason *node_id* is expected to fail: by exact, unparametrized or module id."""
    reason = entries.get(node_id)
    if reason is None and node_id.endswith("]") and "[" in node_id:
        reason = entries.get(node_id[: node_id.index("[")])
    if reason is None:
        reason = entries.get(node_id.split("::", 1)[0])
    return reason


def active_os() -> str | None:
    if os.environ.get(ENABLE_ENV) != "1":
        return None
    return PLATFORM_BASELINES.get(sys.platform)


def pytest_configure(config: pytest.Config) -> None:
    os_name = active_os()
    entries = load_baseline(os_name) if os_name else {}
    flaky = load_flaky(os_name) if os_name else {}
    both = sorted(entries.keys() & flaky.keys())
    if both:
        raise pytest.UsageError(
            f"known_failure_baseline_flaky_overlap: {both[0]} is both a known failure "
            "and flaky; keep it in one list"
        )
    config.stash[_ENTRIES] = entries
    config.stash[_FLAKY] = flaky


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector: pytest.Collector):
    report = yield
    entries = collector.config.stash.get(_ENTRIES, {})
    reason = entries.get(collector.nodeid) if isinstance(collector, pytest.Module) else None
    if reason is not None and report.failed:
        report.outcome = "skipped"
        report.longrepr = (
            str(collector.path), 0, f"Skipped: {active_os()} known failure: {reason}"
        )
    return report


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    entries = config.stash.get(_ENTRIES, {})
    flaky = config.stash.get(_FLAKY, {})
    if not (entries or flaky):
        return
    os_name = active_os()
    for item in items:
        flake = baseline_reason(item.nodeid, flaky)
        if flake is not None:
            text = f"{os_name} flaky until {flake['fix_item']} lands: {flake['reason']}"
            item.stash[_FLAKY_REASON] = text
            item.add_marker(pytest.mark.xfail(strict=False, reason=text))
            continue
        reason = baseline_reason(item.nodeid, entries)
        if reason is not None:
            text = f"{os_name} known failure: {reason}"
            item.stash[_REASON] = text
            item.add_marker(pytest.mark.xfail(strict=True, reason=text))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):
    """Judge a listed test once its teardown is known.

    A listed test is expected to fail in some phase. pytest's strict xfail
    judges the call alone, so a body that passes ahead of a failing teardown
    would read as fixed. The call's XPASS is held until teardown: a failing
    teardown makes the whole test the expected failure, and a clean one fails
    the run at teardown with an explicit ``[XPASS(strict)]`` message.
    """
    report = yield
    flake = item.stash.get(_FLAKY_REASON, None)
    if flake is not None:
        if report.when == "teardown" and call.excinfo is not None:
            report.outcome = "skipped"
            report.wasxfail = flake
        return report
    reason = item.stash.get(_REASON, None)
    if reason is None:
        return report
    if report.when == "call" and report.failed and not hasattr(report, "wasxfail") and call.excinfo is None:
        item.stash[_PASSED_SO_FAR] = True
        report.outcome = "passed"
        report.longrepr = None
    elif report.when == "teardown" and call.excinfo is not None:
        report.outcome = "skipped"
        report.wasxfail = reason
    elif report.when == "teardown" and item.stash.get(_PASSED_SO_FAR, False):
        report.outcome = "failed"
        report.longrepr = f"{XPASS_MARK} {item.nodeid} passed: {reason}; delete its known-failure entry"
    return report
