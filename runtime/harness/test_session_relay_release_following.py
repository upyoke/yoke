"""The standing relay follows only its environment's served release."""

from __future__ import annotations

from yoke_cli.transport import control_plane_payload
from yoke_harness.session_relay import ServeOnceOutcome
from yoke_harness.session_relay_daemon import serve_forever


PINNED_RELEASE = "0.1.1+launch.365"
SERVED_RELEASE = f"v{PINNED_RELEASE}"
NEXT_SERVED_RELEASE = "v0.1.1+launch.366"


def _served_cycle(build: str):
    def cycle(**_kwargs) -> ServeOnceOutcome:
        control_plane_payload.observe_server_build(build)
        return ServeOnceOutcome("active", 1)

    return cycle


def test_served_build_change_repins_and_replaces_the_process(tmp_path) -> None:
    replacement = tmp_path / "venv" / "bin" / "yoke"
    reloaded: list[tuple[object, object]] = []
    pins: list[str] = []

    def pin(build: str):
        pins.append(build)
        return replacement

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=_served_cycle(NEXT_SERVED_RELEASE),
        idle_tick_seconds=0.01,
        install_signals=False,
        pinned_release=PINNED_RELEASE,
        pin_served_release=pin,
        reload_argv=["--env", "prod", "relay", "serve"],
        reload_exec=lambda argv=None, executable=None: reloaded.append(
            (argv, executable)
        ),
    )

    assert outcome.reason == "served_build_changed"
    assert outcome.cycles == 1
    assert pins == [NEXT_SERVED_RELEASE]
    assert reloaded == [(["--env", "prod", "relay", "serve"], str(replacement))]


def test_checkout_change_does_not_repin_before_the_environment_deploy(
    tmp_path,
) -> None:
    checkout_source = tmp_path / "session_relay_contract.py"
    checkout_source.write_text("request = 'old'\n", encoding="utf-8")
    pins: list[str] = []
    cycles = 0

    def change_checkout(**_kwargs) -> ServeOnceOutcome:
        nonlocal cycles
        cycles += 1
        control_plane_payload.observe_server_build(SERVED_RELEASE)
        if cycles == 1:
            checkout_source.write_text("request = 'new'\n", encoding="utf-8")
        return ServeOnceOutcome("active", 1)

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=change_checkout,
        stop_after_cycles=5,
        idle_tick_seconds=0.001,
        install_signals=False,
        pinned_release=PINNED_RELEASE,
        pin_served_release=lambda build: pins.append(build),
    )

    assert outcome.cycles == 5
    assert checkout_source.read_text(encoding="utf-8") == "request = 'new'\n"
    assert pins == []


def test_failed_pin_keeps_the_working_process_and_retries_after_each_poll(
    tmp_path,
) -> None:
    reloaded: list[object] = []
    pins: list[str] = []

    class FetchFailed(RuntimeError):
        code = "index_fetch_failed"

    def fail(build: str):
        pins.append(build)
        raise FetchFailed("index unavailable; recovery: retry relay install")

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=_served_cycle(NEXT_SERVED_RELEASE),
        stop_after_cycles=2,
        idle_tick_seconds=0.001,
        install_signals=False,
        pinned_release=PINNED_RELEASE,
        pin_served_release=fail,
        reload_exec=lambda argv=None, **_kw: reloaded.append(argv),
    )

    assert outcome.reason == "cycle_cap"
    assert pins == [NEXT_SERVED_RELEASE, NEXT_SERVED_RELEASE]
    assert reloaded == []


def test_backoff_does_not_retry_a_pin_without_a_fresh_handshake(tmp_path) -> None:
    pins: list[str] = []
    control_plane_payload.observe_server_build(NEXT_SERVED_RELEASE)

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=lambda **_kwargs: ServeOnceOutcome("backoff"),
        stop_after_cycles=2,
        idle_tick_seconds=0.001,
        install_signals=False,
        pinned_release=PINNED_RELEASE,
        pin_served_release=lambda build: pins.append(build),
    )

    assert outcome.reason == "cycle_cap"
    assert pins == []
