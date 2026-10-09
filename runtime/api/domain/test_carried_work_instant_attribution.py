"""Native landing attribution compares exact durations against qualified Git facts."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import deployment_run_carried_work_sources as sources
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.deployment_run_carried_work_repository import (
    RepositoryProviderSource,
)

STAMP = parse_instant("1969-12-31T23:59:59.123456Z")


def _resolve(monkeypatch, landed, commit_times):
    row = (7, landed, None, None, None, None)
    monkeypatch.setattr(sources, "_safe_rows", lambda *args, **kwargs: [row])
    resolved = {}
    sources._resolve_item_metadata(
        object(),
        project_id=1,
        source=SimpleNamespace(commit_time=lambda commit: commit_times[commit]),
        base="base",
        head="head",
        commits=list(commit_times),
        known_items={7: "YOK-7"},
        resolved=resolved,
        warnings=[],
    )
    return resolved


@pytest.mark.parametrize("extra,expected", [(0, {"a": {7}}), (1, {})])
def test_native_landing_cutoff_retains_microsecond_boundary(
    monkeypatch, extra, expected
):
    commit = STAMP + timedelta(seconds=600, microseconds=extra)
    assert _resolve(monkeypatch, STAMP, {"a": commit}) == expected


def test_equal_distance_commits_do_not_infer_an_owner(monkeypatch):
    assert (
        _resolve(
            monkeypatch,
            STAMP,
            {
                "a": STAMP - timedelta(microseconds=1),
                "b": STAMP + timedelta(microseconds=1),
            },
        )
        == {}
    )


def test_qualified_external_offset_equals_native_landing(monkeypatch):
    assert _resolve(monkeypatch, STAMP, {"a": "1970-01-01T05:29:59.123456+05:30"}) == {
        "a": {7}
    }


@pytest.mark.parametrize("bad", [None, "", "1969-12-31", "1969-12-31T23:59:59", 0])
def test_missing_or_unqualified_external_commit_does_not_attribute(monkeypatch, bad):
    assert _resolve(monkeypatch, STAMP, {"a": bad}) == {}


def test_malformed_internal_landing_is_not_assumed_utc(monkeypatch):
    with pytest.raises(InvalidInstant):
        _resolve(monkeypatch, "1969-12-31T23:59:59", {"a": STAMP})


@pytest.mark.parametrize("origin", ["checkout", "provider"])
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1969-12-31T23:59:59.123456Z", STAMP),
        ("1970-01-01T05:29:59.123456+05:30", STAMP),
        (STAMP, STAMP),
        (None, None),
        ("", None),
        ("1969-12-31", None),
        ("1969-12-31T23:59:59", None),
        (0, None),
    ],
)
def test_source_commit_clock_is_native_without_changing_raw_evidence(
    monkeypatch, origin, raw, expected
):
    if origin == "checkout":
        source = LocalCheckoutSource("/repo")
        fact = (raw, "opaque clock 1969-12-31", "author")
        monkeypatch.setattr(source, "_fact", lambda _: fact)

        def retained():
            return source._fact("a")

        original = fact
    else:
        source = RepositoryProviderSource("owner/repo", "token")
        original = {
            "committed_at": raw,
            "message": "opaque clock 1969-12-31",
            "author": "author",
        }
        source._graph["a"] = original.copy()

        def retained():
            return source._graph["a"]

    assert source.commit_time("a") == expected
    assert retained() == original
    assert source.commit_message("a") == "opaque clock 1969-12-31"
    assert source.commit_author("a") == "author"
