"""Native model availability: parsing, staleness, and the relay heartbeat."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.session_control.native_model_parsers import (
    codex_next_cursor,
    cursor_token_effort,
    parse_codex_models,
    parse_cursor_models,
)
from yoke_contracts.session_control.native_models import (
    MAX_MODELS_PER_SURFACE,
    NATIVE_MODEL_SURFACES,
    NO_ADAPTER_REASON,
    TRUNCATED_REASON,
    available_models,
    empty_reading,
    models_reading,
    native_model,
    sanitize_native_models,
    stale_reading,
)
from yoke_harness import session_relay_native_models as observer


# Recorded from an installed cursor-agent: prose lines the parser must ignore,
# a token with no effort suffix, and the effort/speed variants of one model.
CURSOR_OUTPUT = """Available models

auto - Auto (default)
cursor-grok-4.6-low - Cursor Grok 4.6 Low
cursor-grok-4.6-xhigh - Cursor Grok 4.6 Extra High
cursor-grok-4.6-xhigh-fast - Cursor Grok 4.6 Extra High Fast
"""

# Recorded from an installed codex app-server. The retiring model is what
# proves replacement metadata survives; the hidden one must never be offered.
CODEX_PAGE = {
    "data": [
        {
            "id": "gpt-6-astra",
            "model": "gpt-6-astra",
            "displayName": "GPT-6-Astra",
            "hidden": False,
            "supportedReasoningEfforts": [
                {"reasoningEffort": "low"},
                {"reasoningEffort": "xhigh"},
                {"reasoningEffort": "ultra"},
            ],
            "defaultReasoningEffort": "medium",
            "upgrade": None,
            "upgradeInfo": None,
        },
        {
            "id": "gpt-5.4-mini",
            "displayName": "GPT-5.4-Mini",
            "hidden": False,
            "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
            "upgrade": "gpt-5.6-luna",
            "upgradeInfo": {"model": "gpt-5.6-luna", "retirementAt": 1788202800},
        },
        {"id": "internal-preview", "hidden": True},
    ],
    "nextCursor": None,
}


def test_cursor_rows_parse_with_their_encoded_effort() -> None:
    models = parse_cursor_models(CURSOR_OUTPUT)

    assert [entry["model"] for entry in models] == [
        "auto",
        "cursor-grok-4.6-low",
        "cursor-grok-4.6-xhigh",
        "cursor-grok-4.6-xhigh-fast",
    ]
    assert models[0]["description"] == "Auto (default)"
    assert models[2]["reasoning_efforts"] == ["xhigh"]
    # The speed variant is its own selectable token, and its reasoning option
    # is still the one the token encodes.
    assert models[3]["reasoning_efforts"] == ["xhigh"]


def test_cursor_effort_suffix_prefers_the_longest_match() -> None:
    assert cursor_token_effort("model-xhigh") == "xhigh"
    assert cursor_token_effort("model-high") == "high"
    assert cursor_token_effort("model-high-fast") == "high"
    assert cursor_token_effort("composer-2.5") is None


def test_codex_models_carry_efforts_and_replacement_metadata() -> None:
    models = parse_codex_models(CODEX_PAGE)

    assert [entry["model"] for entry in models] == ["gpt-6-astra", "gpt-5.4-mini"]
    assert models[0]["reasoning_efforts"] == ["low", "xhigh", "ultra"]
    assert models[0]["default_reasoning_effort"] == "medium"
    assert models[1]["replaced_by"] == "gpt-5.6-luna"
    assert models[1]["retires_at"] == "2026-08-31T19:00:00Z"
    assert codex_next_cursor(CODEX_PAGE) is None


def test_absent_vendor_fields_are_omitted_rather_than_carried_as_nulls() -> None:
    entry = native_model("composer-2.5", description="Composer 2.5")

    assert entry == {"model": "composer-2.5", "description": "Composer 2.5"}


def test_reading_names_its_own_truncation() -> None:
    over = [
        native_model(f"model-{index}") for index in range(MAX_MODELS_PER_SURFACE + 5)
    ]

    reading = models_reading("cursor-cli", over, source="s", observed_at="t")

    assert len(reading["models"]) == MAX_MODELS_PER_SURFACE
    assert reading["reason"] == TRUNCATED_REASON


def test_failed_probe_keeps_the_models_last_seen_and_marks_them_stale() -> None:
    previous = models_reading(
        "codex-cli",
        parse_codex_models(CODEX_PAGE),
        source="codex app-server model/list",
        observed_at="2026-09-07T14:00:00Z",
    )

    stale = stale_reading(previous, "codex-cli", "app_server_timeout")

    assert stale["status"] == "stale"
    assert stale["reason"] == "app_server_timeout"
    # The original observation time survives, because that is when these
    # models were actually seen.
    assert stale["observed_at"] == "2026-09-07T14:00:00Z"
    assert available_models(stale) == ("gpt-6-astra", "gpt-5.4-mini")


def test_a_surface_that_never_answered_reports_unknown_not_stale() -> None:
    assert stale_reading(None, "codex-cli", "cli_unavailable")["status"] == "unknown"
    assert stale_reading({"models": []}, "codex-cli", "x")["status"] == "unknown"


def test_fresh_success_with_no_models_is_not_reported_as_a_clean_answer() -> None:
    empty_success = {"surface": "codex-cli", "status": "ok", "models": []}

    cleaned = sanitize_native_models({"codex-cli": empty_success})

    assert cleaned["codex-cli"]["status"] == "unknown"


def test_sanitize_drops_unknown_surfaces_and_unexpected_keys() -> None:
    cleaned = sanitize_native_models(
        {
            "codex-cli": {
                "status": "ok",
                "models": [{"model": "gpt-6-astra", "access_token": "secret"}],
            },
            "not-a-surface": {"status": "ok", "models": [{"model": "x"}]},
        }
    )

    assert sorted(cleaned) == ["codex-cli"]
    assert sorted(cleaned["codex-cli"]["models"][0]) == ["model"]


def test_surface_without_an_adapter_names_the_absence_rather_than_probing(
    tmp_path: Path,
) -> None:
    readings = observer.observe_native_models(
        ("claude-cli", "cursor-desktop"), state_dir=tmp_path
    )

    for surface in ("claude-cli", "cursor-desktop"):
        assert readings[surface]["status"] == "unsupported"
        assert readings[surface]["reason"] == NO_ADAPTER_REASON


def test_every_known_surface_is_answered_so_desktop_never_inherits_the_cli(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setitem(
        observer.NATIVE_MODEL_PROBES,
        "cursor-cli",
        lambda *, observed_at: models_reading(
            "cursor-cli",
            parse_cursor_models(CURSOR_OUTPUT),
            source="cursor-agent --list-models",
            observed_at=observed_at,
        ),
    )
    monkeypatch.setitem(
        observer.NATIVE_MODEL_PROBES,
        "codex-cli",
        lambda *, observed_at: empty_reading("codex-cli", "unknown", "cli_unavailable"),
    )

    readings = observer.observe_native_models(state_dir=tmp_path)

    assert sorted(readings) == sorted(NATIVE_MODEL_SURFACES)
    assert readings["cursor-cli"]["status"] == "ok"
    # The desktop app shares a vendor with an answering CLI and still reports
    # its own absence.
    assert readings["cursor-desktop"]["status"] == "unsupported"


def test_cached_readings_serve_the_next_poll_without_probing_again(
    tmp_path: Path, monkeypatch
) -> None:
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
        ("cursor-cli",), state_dir=tmp_path, now=1_000.0
    )
    within = observer.observe_native_models(
        ("cursor-cli",), state_dir=tmp_path, now=1_010.0
    )
    beyond = observer.observe_native_models(
        ("cursor-cli",),
        state_dir=tmp_path,
        now=1_000.0 + observer.NATIVE_MODEL_REFRESH_SECONDS + 1,
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
    observer.observe_native_models(("cursor-cli",), state_dir=tmp_path, now=1_000.0)
    observer.observe_native_models(
        ("cursor-cli",), state_dir=tmp_path, now=1_001.0, force=True
    )

    assert len(calls) == 2


def test_a_probe_that_raises_is_named_rather_than_collapsed(
    tmp_path: Path, monkeypatch
) -> None:
    def probe(*, observed_at: str) -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setitem(observer.NATIVE_MODEL_PROBES, "cursor-cli", probe)

    reading = observer.observe_native_models(("cursor-cli",), state_dir=tmp_path)[
        "cursor-cli"
    ]

    assert reading["status"] == "unknown"
    assert reading["reason"] == "probe_raised_RuntimeError"


def test_a_later_failure_does_not_withdraw_the_models_already_published(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setitem(
        observer.NATIVE_MODEL_PROBES,
        "cursor-cli",
        lambda *, observed_at: models_reading(
            "cursor-cli",
            parse_cursor_models(CURSOR_OUTPUT),
            source="cursor-agent --list-models",
            observed_at="2026-09-07T14:00:00Z",
        ),
    )
    observer.observe_native_models(("cursor-cli",), state_dir=tmp_path, now=1_000.0)
    monkeypatch.setitem(
        observer.NATIVE_MODEL_PROBES,
        "cursor-cli",
        lambda *, observed_at: empty_reading(
            "cursor-cli", "unknown", "list_models_timeout"
        ),
    )

    reading = observer.observe_native_models(
        ("cursor-cli",),
        state_dir=tmp_path,
        now=1_000.0 + observer.NATIVE_MODEL_REFRESH_SECONDS + 1,
    )["cursor-cli"]

    assert reading["status"] == "stale"
    assert reading["reason"] == "list_models_timeout"
    assert reading["observed_at"] == "2026-09-07T14:00:00Z"
    assert "auto" in available_models(reading)


def test_a_cache_written_by_another_shape_is_discarded_not_reported(
    tmp_path: Path,
) -> None:
    path = tmp_path / observer.NATIVE_MODEL_CACHE_FILE_NAME
    path.write_text('{"schema_version": 0, "surfaces": {"cursor-cli": {}}}')

    assert observer._read_cache(tmp_path)["surfaces"] == {}


def test_heartbeat_carries_the_observed_readings(monkeypatch, tmp_path: Path) -> None:
    # Availability only ever reaches the control plane inside this payload,
    # so a reading the observer produced but the heartbeat drops is invisible.
    from yoke_harness import session_relay_inventory as inventory_module

    reading = models_reading(
        "cursor-cli", [native_model("auto")], source="s", observed_at="t"
    )
    monkeypatch.setattr(
        inventory_module,
        "ensure_machine_id",
        lambda: "11111111-1111-4111-8111-111111111111",
    )
    monkeypatch.setattr(
        inventory_module.machine_config, "configured_projects", lambda **_kwargs: []
    )
    monkeypatch.setattr(inventory_module, "local_handshake_version", lambda: "source")
    monkeypatch.setattr(inventory_module, "observe_plan_limits", lambda *_a, **_k: {})
    monkeypatch.setattr(
        inventory_module,
        "observe_native_models",
        lambda **_kwargs: {"cursor-cli": reading},
    )

    inventory = inventory_module.collect_cached_inventory(state_dir=tmp_path)

    assert inventory.surface_native_models == {"cursor-cli": reading}
    assert inventory.claim_payload()["native_models"] == {"cursor-cli": reading}
