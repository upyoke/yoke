"""A healthy burst is staggered briefly; unsafe capacity starts no native."""

import pytest

from yoke_contracts.machine_config import native_capacity as capacity
from yoke_harness import session_launch_admission as admission
from yoke_harness.session_relay_runtime import RelayAdapterResult, RelayExecutionContext


@pytest.mark.parametrize(
    ("memory", "total", "free", "code"),
    [
        (capacity.MIN_NATIVE_FREE_MEMORY_BYTES - 1, 0, 0, "native_memory_headroom_low"),
        (capacity.MIN_NATIVE_FREE_MEMORY_BYTES, 1024**3, 1, "native_swap_headroom_low"),
        (None, 0, 0, "native_capacity_unreadable"),
        (1024**3, None, None, "native_capacity_unreadable"),
        (1024**3, 0, 0, None),
        (1024**3, 1024**3, capacity.MIN_NATIVE_SWAP_FREE_BYTES, None),
    ],
)
def test_capacity_names_unsafe_readings(memory, total, free, code):
    assert capacity.NativeCapacity(memory, total, free).refusal() == code


def test_burst_starts_at_short_intervals_and_rechecks_each_spawn(monkeypatch):
    monkeypatch.setattr(admission, "_LAST_SPAWN", None)
    monkeypatch.setattr(admission, "NATIVE_SPAWN_STAGGER_SECONDS", 3)
    elapsed = [0.0]
    readings = []
    starts = []

    def sleep(seconds):
        elapsed[0] += seconds

    def probe():
        readings.append(elapsed[0])
        return capacity.NativeCapacity(2 * 1024**3, 0, 0)

    for _ in range(5):
        with admission.native_spawn_admission(
            probe=probe, clock=lambda: elapsed[0], sleeper=sleep
        ):
            starts.append(elapsed[0])
    assert starts == [0, 3, 6, 9, 12]
    assert readings == starts


def test_capacity_drop_mid_burst_refuses_the_next_native(monkeypatch):
    monkeypatch.setattr(admission, "_LAST_SPAWN", None)
    starts = []
    for reading in [
        capacity.NativeCapacity(2 * 1024**3, 0, 0),
        capacity.NativeCapacity(1, 0, 0),
    ]:
        try:
            with admission.native_spawn_admission(
                probe=lambda: reading, clock=lambda: 10, sleeper=lambda _: None
            ):
                starts.append(True)
        except admission.NativeCapacityRefusal as exc:
            assert exc.code == "native_memory_headroom_low"
            assert "Recovery:" in str(exc)
    assert starts == [True]


def test_capacity_refusal_is_a_named_launch_result(tmp_path):
    context = RelayExecutionContext(
        "launch", "job", "lease", "codex-cli", 1, tmp_path, "job"
    )

    def adapter(_):
        raise admission.NativeCapacityRefusal("native_swap_headroom_low")

    result = admission.run_admitted_adapter(context, adapter)
    assert isinstance(result, RelayAdapterResult)
    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == "native_swap_headroom_low"


def test_macos_swap_probe(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(capacity.sys, "platform", "darwin")
    monkeypatch.setattr(
        capacity.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout="total = 1024.00M used = 256.00M free = 768.00M"
        ),
    )
    assert capacity.swap_headroom() == (1024**3, 768 * 1024**2)


def test_linux_swap_probe(monkeypatch):
    monkeypatch.setattr(capacity.sys, "platform", "linux")
    monkeypatch.setattr(
        capacity.Path,
        "read_text",
        lambda _: "SwapTotal: 1048576 kB\nSwapFree: 524288 kB\n",
    )
    assert capacity.swap_headroom() == (1024**3, 512 * 1024**2)


def test_supervised_spawn_refusal_starts_no_process(monkeypatch, tmp_path):
    from uuid import uuid4
    from yoke_harness.session_relay_native_spawn import spawn_supervised_native

    monkeypatch.setattr(
        admission, "observe_native_capacity", lambda: capacity.NativeCapacity(1, 0, 0)
    )
    spawned = []
    with pytest.raises(
        admission.NativeCapacityRefusal, match="native_memory_headroom_low"
    ):
        spawn_supervised_native(
            ["vendor"],
            checkout=tmp_path,
            environment={},
            attempt_id=str(uuid4()),
            native_session_id=None,
            binary_source="path",
            supervision_kind="launch",
            state_dir=tmp_path,
            process_factory=lambda *a, **kw: spawned.append(True),
        )
    assert spawned == []


@pytest.mark.parametrize("surface", ["codex-cli", "codex-desktop"])
def test_detached_codex_worker_preserves_capacity_refusal(
    monkeypatch, tmp_path, surface
):
    from io import BytesIO, StringIO
    import json
    from yoke_harness import session_relay_codex_cli_process as cli
    from yoke_harness import session_relay_codex_app_server_process as desktop
    from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
    from yoke_harness.session_relay_codex import CodexNativeRequest
    from yoke_harness.session_relay_codex_worker_protocol import request_payload

    request = CodexNativeRequest(
        "launch",
        "launch",
        surface,
        "supported",
        tmp_path,
        None,
        None,
        None,
        None,
        None,
        "instruction",
        "instruction",
        launch_attestation="secret",
    )
    module = cli if surface == "codex-cli" else desktop

    def refuse(_):
        admission.spawn_admitted_process(["vendor"])

    monkeypatch.setattr(module, "_run_in_worker", refuse)
    monkeypatch.setattr(
        admission, "observe_native_capacity", lambda: capacity.NativeCapacity(1, 0, 0)
    )
    output = StringIO()
    assert (
        module.worker_main(
            stdin=BytesIO(json.dumps(request_payload(request)).encode()),
            stdout=output,
            environ={
                LAUNCH_CONTEXT_ENV: json.dumps(
                    {"launch_id": "launch", "attestation": "secret"}
                )
            },
        )
        == 0
    )
    outcome = json.loads(output.getvalue())
    assert outcome["state"] == "not_created"
    assert outcome["failure_code"] == "native_memory_headroom_low"
    assert outcome["pid"] is None


def test_detached_owner_refusal_starts_no_process(monkeypatch, tmp_path):
    from yoke_harness.session_relay_detached_worker import run_detached_json_worker

    monkeypatch.setattr(
        admission, "observe_native_capacity", lambda: capacity.NativeCapacity(1, 0, 0)
    )
    started = []
    with pytest.raises(admission.NativeCapacityRefusal):
        run_detached_json_worker(
            module="vendor",
            checkout=tmp_path,
            environment={},
            payload={},
            decode=lambda value: value,
            initial_failure=None,
            uncertain_failure=None,
            process_factory=lambda *a, **kw: started.append(True),
        )
    assert started == []
