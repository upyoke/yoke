"""Relay probe cadence and persisted clocks preserve exact instants."""

import json
from datetime import timedelta
import pytest
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_harness import session_relay_health as health
from yoke_harness.session_relay_probe_cache import read_probe_cache, write_probe_cache

from yoke_contracts.session_control.native_model_parsers import parse_cursor_models

from pathlib import Path

from runtime.harness.session_relay_clock_test_support import at
from yoke_contracts.session_control.native_models import models_reading, native_model
from yoke_contracts.session_control.plan_limits import unknown_reading
from yoke_harness import session_relay_native_models as observer
from yoke_harness import session_relay_plan_limits as limits

NOW = "2026-08-30T01:00:00.000000Z"


def test_cached_readings_serve_the_next_poll_without_probing_again(
    tmp_path: Path, monkeypatch
) -> None:
    from runtime.harness.test_session_relay_native_models import CURSOR_OUTPUT

    calls: list[str] = []

    def probe(*, observed_at: str) -> dict[str, object]:
        calls.append(observed_at)
        return models_reading(
            "cursor-cli",
            parse_cursor_models(CURSOR_OUTPUT),
            source="cursor-agent --list-models",
            observed_at=observed_at,
        )

    monkeypatch.setitem(observer.NATIVE_MODEL_PROBES, "cursor-cli", probe)
    first = observer.observe_native_models(
        ("cursor-cli",), state_dir=tmp_path, now=at(1_000.0)
    )
    within = observer.observe_native_models(
        ("cursor-cli",), state_dir=tmp_path, now=at(1_010.0)
    )
    beyond = observer.observe_native_models(
        ("cursor-cli",),
        state_dir=tmp_path,
        now=at(1_000.0 + observer.NATIVE_MODEL_REFRESH_SECONDS + 1),
    )

    assert len(calls) == 2
    assert first["cursor-cli"]["models"] == within["cursor-cli"]["models"]
    assert beyond["cursor-cli"]["status"] == "ok"


def test_forced_refresh_ignores_the_cadence(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def probe(*, observed_at: str) -> dict[str, object]:
        calls.append(observed_at)
        return models_reading(
            "cursor-cli", [native_model("auto")], source="s", observed_at=observed_at
        )

    monkeypatch.setitem(observer.NATIVE_MODEL_PROBES, "cursor-cli", probe)
    observer.observe_native_models(("cursor-cli",), state_dir=tmp_path, now=at(1_000.0))
    observer.observe_native_models(
        ("cursor-cli",), state_dir=tmp_path, now=at(1_001.0), force=True
    )

    assert len(calls) == 2


def test_fresh_cache_skips_a_second_probe(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def _fake(surface: str, observed_at: str) -> dict:
        calls.append(surface)
        return unknown_reading(surface, "stale_credential", observed_at=observed_at)

    monkeypatch.setattr(limits, "_probe_one", _fake)
    first = limits.observe_plan_limits(
        ("claude-cli",), state_dir=tmp_path, now=at(1_000.0), clock=lambda: NOW
    )
    second = limits.observe_plan_limits(
        ("claude-cli",), state_dir=tmp_path, now=at(1_060.0), clock=lambda: NOW
    )
    third = limits.observe_plan_limits(
        ("claude-cli",),
        state_dir=tmp_path,
        now=at(1_000.0 + limits.PLAN_LIMIT_REFRESH_SECONDS + 1),
        clock=lambda: NOW,
    )
    assert calls == ["claude-cli", "claude-cli"]
    for readings in (first, second, third):
        assert readings["claude-cli"]["windows"][0]["reason"] == "stale_credential"


@pytest.mark.parametrize("kind", ["models", "limits"])
def test_probe_cache_keeps_exact_native_cadence_and_canonical_json(
    tmp_path, monkeypatch, kind
):
    module = observer if kind == "models" else limits
    observe = (
        module.observe_native_models if kind == "models" else module.observe_plan_limits
    )
    window = (
        module.NATIVE_MODEL_REFRESH_SECONDS
        if kind == "models"
        else module.PLAN_LIMIT_REFRESH_SECONDS
    )
    filename = (
        module.NATIVE_MODEL_CACHE_FILE_NAME
        if kind == "models"
        else module.PLAN_LIMIT_CACHE_FILE_NAME
    )
    calls = []

    def probe(surface, observed_at):
        calls.append(observed_at)
        if kind == "models":
            return models_reading(
                surface,
                [native_model("2026-01-01")],
                source="s",
                observed_at=observed_at,
            )
        return unknown_reading(surface, "unavailable", observed_at=observed_at)

    monkeypatch.setattr(module, "_probe_one", probe)
    anchor = parse_instant("1969-12-31T23:59:59.999999Z")
    equivalent = "1969-12-31T18:59:59.999999-05:00"
    observe(
        ("cursor-cli",), state_dir=tmp_path, now=equivalent, clock=lambda: equivalent
    )
    document = json.loads((tmp_path / filename).read_text())
    assert (
        document["probed_at"]
        == document["surfaces"]["cursor-cli"]["observed_at"]
        == format_instant(anchor)
    )
    if kind == "models":
        assert document["surfaces"]["cursor-cli"]["models"][0]["model"] == "2026-01-01"
    observe(
        ("cursor-cli",),
        state_dir=tmp_path,
        now=anchor + timedelta(seconds=window, microseconds=-1),
    )
    assert len(calls) == 1
    observe(("cursor-cli",), state_dir=tmp_path, now=anchor + timedelta(seconds=window))
    assert len(calls) == 2
    observe(("cursor-cli",), state_dir=tmp_path, now=anchor)
    assert len(calls) == 3  # A future cache entry cannot prove current freshness.


@pytest.mark.parametrize("bad", [0, 1000.25, "", "1969-12-31", "1969-12-31T23:59:59"])
def test_probe_cache_rejects_non_instants_without_creating_a_file(tmp_path, bad):
    path = tmp_path / "not-created" / "cache.json"
    with pytest.raises(InvalidInstant):
        write_probe_cache(path, {"schema_version": 2, "probed_at": bad, "surfaces": {}})
    assert not path.parent.exists()
    path = tmp_path / "invalid.json"
    path.write_text(
        json.dumps({"schema_version": 2, "probed_at": bad, "surfaces": {"opaque": {}}})
    )
    assert read_probe_cache(path, 2) == {
        "schema_version": 2,
        "probed_at": None,
        "surfaces": {},
    }


def test_probe_cache_has_explicit_null_and_discards_an_obsolete_shape(tmp_path):
    path = tmp_path / "cache.json"
    write_probe_cache(path, {"schema_version": 2, "probed_at": None, "surfaces": {}})
    assert json.loads(path.read_text())["probed_at"] is None
    assert read_probe_cache(path, 2)["probed_at"] is None
    assert read_probe_cache(path, 3)["surfaces"] == {}


def test_relay_health_clocks_are_canonical_and_quarantine_preserves_bytes(tmp_path):
    from hashlib import sha256
    from yoke_contracts.session_control.relay_health import sanitize_relay_health

    stamp = "1969-12-31T18:59:59.999999-05:00"
    canonical = format_instant(stamp)
    health.record_report_failure(tmp_path, error_code="offline", now=stamp)
    health.record_report_failure(
        tmp_path,
        error_code="offline",
        now=parse_instant(stamp) + timedelta(microseconds=1),
    )
    document = json.loads((tmp_path / health.RELAY_HEALTH_FILE_NAME).read_text())
    assert document["report_failure"]["first_failed_at"] == canonical
    assert document["report_failure"]["last_failed_at"] == "1970-01-01T00:00:00.000000Z"
    health.record_relay_run_refusal(
        tmp_path,
        pinned_release="opaque",
        local_revision="candidate",
        server_revision="serving",
        ahead_by=1,
        now=stamp,
    )
    source = tmp_path / "report.json"
    body = b'{"clock-looking-text":"2026-01-01","value":7}'
    source.write_bytes(body)
    metadata = health.quarantine_report(
        source, {}, tmp_path, error_code="report_conflict", attempts=3, now=stamp
    )
    assert metadata["quarantined_at"] == canonical
    assert metadata["payload_sha256"] == sha256(body).hexdigest()
    assert Path(metadata["preserved_path"]).read_bytes() == body
    assert (
        sanitize_relay_health({"quarantined_reports": [metadata]})[
            "quarantined_reports"
        ][0]["quarantined_at"]
        == canonical
    )


@pytest.mark.parametrize("bad", ["", "2026-01-01", "2026-01-01T00:00:00", 0])
def test_relay_health_clock_admission_precedes_file_mutation(tmp_path, bad):
    with pytest.raises(InvalidInstant):
        health.record_report_failure(tmp_path, error_code="offline", now=bad)
    assert not list(tmp_path.iterdir())
