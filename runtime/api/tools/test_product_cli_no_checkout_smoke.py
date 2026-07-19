from __future__ import annotations

import json
from pathlib import Path

from yoke_core.tools import product_cli_no_checkout_smoke_core as core
from yoke_core.tools import product_cli_no_checkout_smoke_steps as steps
from yoke_core.tools.checkout_clean_room_smoke_helpers import CommandResult


class FakeRunner:
    """Canned StepRunner: pops (returncode, stdout, stderr) per step, FIFO."""

    def __init__(self, responses: dict) -> None:
        self.responses = {step: list(items) for step, items in responses.items()}
        self.calls: list = []

    def __call__(self, command: list, step: str) -> CommandResult:
        argv = [str(part) for part in command]
        self.calls.append((step, argv))
        returncode, stdout, stderr = self.responses[step].pop(0)
        return CommandResult(step=step, command=argv, cwd="/fake",
                             returncode=returncode, stdout=stdout, stderr=stderr)


def make_ctx(tmp_path: Path, *, online: bool = False) -> steps.SmokeContext:
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True, exist_ok=True)
    venv_bin = tmp_path / "venv" / "bin"
    return steps.SmokeContext(
        api_url="https://api.example.test",
        online=online,
        project_dir=project_dir,
        machine_home=machine_home,
        yoke=venv_bin / "yoke",
        venv_python=venv_bin / "python",
        token_path=machine_home / "smoke.token",
    )


def status_payload(ok: bool, codes=(), envs=None, message: str = "") -> str:
    return json.dumps({
        "ok": ok,
        "issues": [
            {"severity": "error", "code": code, "message": message}
            for code in codes
        ],
        "connection": {"envs": list(envs or [])},
    })


# connection set + project register + ok-true status, in dispatch order.
BOOTSTRAP_OK_RESPONSES = [
    (0, "{}", ""), (0, "{}", ""),
    (0, status_payload(True, (), envs=["smoke"]), ""),
]


def write_owner_only_config(ctx: steps.SmokeContext) -> None:
    ctx.config_path.write_text("{}\n", encoding="utf-8")
    ctx.config_path.chmod(0o600)


def test_missing_config_step_requires_codes_and_nonzero_exit(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    both_codes = status_payload(False, ("config_missing", "connections_required"))
    good = steps.step_missing_config(ctx, FakeRunner({
        steps.STEP_MISSING_CONFIG: [(1, both_codes, "")],
    }))
    assert good["status"] == steps.STATUS_PASS
    assert good["evidence"]["issue_codes"] == [
        "config_missing", "connections_required",
    ]

    exit_zero = steps.step_missing_config(ctx, FakeRunner({
        steps.STEP_MISSING_CONFIG: [(0, both_codes, "")],
    }))
    assert exit_zero["status"] == steps.STATUS_FAIL

    missing_code = steps.step_missing_config(ctx, FakeRunner({
        steps.STEP_MISSING_CONFIG: [(1, status_payload(False, ("config_missing",)), "")],
    }))
    assert missing_code["status"] == steps.STATUS_FAIL
    assert any("connections_required" in f for f in missing_code["failures"])


def test_writer_bootstrap_asserts_ok_envs_and_owner_only_config(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    write_owner_only_config(ctx)
    runner = FakeRunner({steps.STEP_WRITER_BOOTSTRAP: BOOTSTRAP_OK_RESPONSES})
    entry = steps.step_writer_bootstrap(ctx, runner)
    assert entry["status"] == steps.STATUS_PASS
    assert entry["evidence"]["connection_envs"] == ["smoke"]
    assert entry["evidence"]["config_mode"] == oct(0o600)
    assert ctx.token_path.read_text(encoding="utf-8").strip() == (
        steps.SMOKE_TOKEN_VALUE
    )
    argv_heads = [argv[1:3] for _, argv in runner.calls]
    assert argv_heads == [
        ["connection", "set"], ["project", "register"], ["status", "--json"],
    ]


def test_writer_bootstrap_failure_modes(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    ctx.config_path.write_text("{}\n", encoding="utf-8")
    ctx.config_path.chmod(0o644)
    loose = steps.step_writer_bootstrap(
        ctx, FakeRunner({steps.STEP_WRITER_BOOTSTRAP: BOOTSTRAP_OK_RESPONSES}),
    )
    assert loose["status"] == steps.STATUS_FAIL
    assert any("not 0600" in failure for failure in loose["failures"])

    ctx.config_path.chmod(0o600)
    not_ok = steps.step_writer_bootstrap(ctx, FakeRunner({
        steps.STEP_WRITER_BOOTSTRAP: [
            (0, "{}", ""), (0, "{}", ""),
            (1, status_payload(False, ("project_mapping_missing",),
                               envs=["smoke"]), ""),
        ],
    }))
    assert not_ok["status"] == steps.STATUS_FAIL
    assert any("ok was not true" in failure for failure in not_ok["failures"])


def test_missing_credential_step_detects_issue(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    write_owner_only_config(ctx)
    entry = steps.step_missing_credential(ctx, FakeRunner({
        steps.STEP_MISSING_CREDENTIAL: [
            (1, status_payload(False, ("credential_missing",)), ""),
        ],
    }))
    assert entry["status"] == steps.STATUS_PASS
    assert entry["evidence"]["missing_credential_path"].endswith(
        "/home/.yoke/secrets/missing.token"
    )
    payload = json.loads(ctx.config_path.read_text(encoding="utf-8"))
    assert payload["connections"][steps.ENV_MISSING_CREDENTIAL][
        "credential_source"
    ]["path"].endswith("/home/.yoke/secrets/missing.token")

    silent = steps.step_missing_credential(ctx, FakeRunner({
        steps.STEP_MISSING_CREDENTIAL: [
            (1, status_payload(False, ()), ""),
        ],
    }))
    assert silent["status"] == steps.STATUS_FAIL


def test_network_unreachable_step_requires_typed_envelope(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    envelope = json.dumps({
        "success": False,
        "error": {"code": "https_transport_failed", "message": "boom"},
    })
    entry = steps.step_network_unreachable(ctx, FakeRunner({
        steps.STEP_NETWORK_UNREACHABLE: [(0, "{}", ""), (1, envelope, "")],
    }))
    assert entry["status"] == steps.STATUS_PASS

    untyped = steps.step_network_unreachable(ctx, FakeRunner({
        steps.STEP_NETWORK_UNREACHABLE: [(0, "{}", ""), (1, "connection refused", "")],
    }))
    assert untyped["status"] == steps.STATUS_FAIL
    assert any("https_transport_failed" in f for f in untyped["failures"])


def test_packs_list_product_client_rejects_import_crashes(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    expected = "error: https_transport_failed: connection refused"
    entry = steps.step_packs_list_product_client(ctx, FakeRunner({
        steps.STEP_PACKS_LIST_PRODUCT: [(1, "", expected)],
    }))
    assert entry["status"] == steps.STATUS_PASS

    import_crash = steps.step_packs_list_product_client(ctx, FakeRunner({
        steps.STEP_PACKS_LIST_PRODUCT: [
            (1, "", "ModuleNotFoundError: No module named 'yoke_core'"),
        ],
    }))
    assert import_crash["status"] == steps.STATUS_FAIL
    assert any("traceback" in failure for failure in import_crash["failures"])


def test_relay_denial_skips_offline_without_calls(tmp_path) -> None:
    ctx = make_ctx(tmp_path, online=False)
    runner = FakeRunner({})
    entry = steps.step_relay_denial(ctx, runner)
    assert entry["status"] == steps.STATUS_SKIPPED_OFFLINE
    assert runner.calls == []


def test_relay_denial_online_requires_denial_code(tmp_path) -> None:
    ctx = make_ctx(tmp_path, online=True)
    denied = steps.step_relay_denial(ctx, FakeRunner({
        steps.STEP_RELAY_DENIAL: [
            (1, json.dumps({"error": {"code": "authentication_malformed"}}), ""),
        ],
    }))
    assert denied["status"] == steps.STATUS_PASS
    assert denied["evidence"]["denial_codes_seen"] == ["authentication_malformed"]

    unreachable = steps.step_relay_denial(ctx, FakeRunner({
        steps.STEP_RELAY_DENIAL: [
            (1, json.dumps({"error": {"code": "https_transport_failed"}}), ""),
        ],
    }))
    assert unreachable["status"] == steps.STATUS_FAIL


def test_unknown_env_step_requires_configured_envs_named(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    named = steps.step_unknown_env(ctx, FakeRunner({
        steps.STEP_UNKNOWN_ENV: [
            (1, status_payload(False, ("active_env",),
                               message="env 'ghost' has no connection "
                                       "(configured: ['offline', 'smoke'])"), ""),
        ],
    }))
    assert named["status"] == steps.STATUS_PASS

    anonymous = steps.step_unknown_env(ctx, FakeRunner({
        steps.STEP_UNKNOWN_ENV: [
            (1, status_payload(False, ("active_env",), message="no such env"), ""),
        ],
    }))
    assert anonymous["status"] == steps.STATUS_FAIL


def test_browser_hygiene_step_project_and_machine_side(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    daemon = {steps.STEP_BROWSER_HYGIENE: [(2, '{"status": "not_running"}', "")]}

    clean = steps.step_browser_hygiene(ctx, FakeRunner(dict(daemon)))
    assert clean["status"] == steps.STATUS_PASS
    assert clean["evidence"]["outcome"] == "not_materialized"

    runtime_dir = ctx.machine_home / steps.BROWSER_RUNTIME_DIR_NAME
    runtime_dir.mkdir()
    bare = steps.step_browser_hygiene(ctx, FakeRunner(dict(daemon)))
    assert bare["status"] == steps.STATUS_FAIL

    (runtime_dir / "package.json").write_text("{}\n", encoding="utf-8")
    materialized = steps.step_browser_hygiene(ctx, FakeRunner(dict(daemon)))
    assert materialized["status"] == steps.STATUS_PASS
    assert materialized["evidence"]["outcome"] == "materialized_machine_side"

    (ctx.project_dir / "node_modules").mkdir()
    polluted = steps.step_browser_hygiene(ctx, FakeRunner(dict(daemon)))
    assert polluted["status"] == steps.STATUS_FAIL
    assert any("node_modules" in failure for failure in polluted["failures"])


def test_no_project_dir_writes_step(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    assert steps.step_no_project_dir_writes(ctx)["status"] == steps.STATUS_PASS

    (ctx.project_dir / "stray.txt").write_text("x", encoding="utf-8")
    dirty = steps.step_no_project_dir_writes(ctx)
    assert dirty["status"] == steps.STATUS_FAIL
    assert dirty["evidence"]["project_dir_entries"] == ["stray.txt"]


def test_execute_steps_offline_happy_path_report(tmp_path) -> None:
    ctx = make_ctx(tmp_path)
    write_owner_only_config(ctx)
    runtime_dir = ctx.machine_home / steps.BROWSER_RUNTIME_DIR_NAME
    runtime_dir.mkdir()
    (runtime_dir / "package.json").write_text("{}\n", encoding="utf-8")
    envelope = json.dumps({"error": {"code": "https_transport_failed"}})
    runner = FakeRunner({
        steps.STEP_MISSING_CONFIG: [
            (1, status_payload(False, ("config_missing", "connections_required")), ""),
        ],
        steps.STEP_WRITER_BOOTSTRAP: BOOTSTRAP_OK_RESPONSES,
        steps.STEP_MISSING_CREDENTIAL: [
            (1, status_payload(False, ("credential_missing",)), ""),
        ],
        steps.STEP_NETWORK_UNREACHABLE: [(0, "{}", ""), (1, envelope, "")],
        steps.STEP_PACKS_LIST_PRODUCT: [
            (1, "", "https_transport_failed: connection refused"),
        ],
        steps.STEP_UNKNOWN_ENV: [
            (1, status_payload(False, ("active_env",),
                               message="(configured: ['smoke'])"), ""),
        ],
        steps.STEP_BROWSER_HYGIENE: [(2, '{"status": "not_running"}', "")],
    })

    results = steps.execute_steps(ctx, runner)

    assert [entry["step"] for entry in results] == [
        steps.STEP_MISSING_CONFIG,
        steps.STEP_WRITER_BOOTSTRAP,
        steps.STEP_MISSING_CREDENTIAL,
        steps.STEP_NETWORK_UNREACHABLE,
        steps.STEP_PACKS_LIST_PRODUCT,
        steps.STEP_RELAY_DENIAL,
        steps.STEP_UNKNOWN_ENV,
        steps.STEP_BROWSER_HYGIENE,
        steps.STEP_NO_PROJECT_WRITES,
    ]
    statuses = {entry["step"]: entry["status"] for entry in results}
    assert statuses[steps.STEP_RELAY_DENIAL] == steps.STATUS_SKIPPED_OFFLINE
    assert all(status != steps.STATUS_FAIL for status in statuses.values())

    report = core.assemble_report(
        api_url=ctx.api_url, online=False, work_dir=tmp_path,
        work_dir_retained=False,
        project_dir=ctx.project_dir, machine_home=ctx.machine_home,
        yoke=ctx.yoke, steps=results, commands=[],
    )
    assert report["ok"] is True
    assert report["work_dir_retained"] is False
    assert "rerun with --keep-work-dir" in report["work_dir_note"]
    assert "smoke.token" in report["machine_home_entries"]


def test_assemble_report_fails_on_any_failed_step(tmp_path) -> None:
    failed = steps.step_entry("x", ["boom"], {})
    skipped = steps.step_entry("y", [], {})
    skipped["status"] = steps.STATUS_SKIPPED_OFFLINE
    report = core.assemble_report(
        api_url="u", online=True, work_dir=tmp_path, work_dir_retained=True,
        project_dir=tmp_path, machine_home=tmp_path, yoke=tmp_path / "s",
        steps=[skipped, failed], commands=[],
    )
    assert report["ok"] is False
    assert report["work_dir_retained"] is True


def test_no_checkout_env_is_isolated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_PG_DSN", "secret")
    monkeypatch.setenv("YOKE_ENV", "ambient")
    env = core.no_checkout_env(
        home=tmp_path / "home",
        machine_home=tmp_path / "home" / ".yoke",
        venv_bin=tmp_path / "venv" / "bin",
    )
    assert "YOKE_PG_DSN" not in env
    # Env routing must come from active_env / per-command --env, and
    # config resolution from YOKE_MACHINE_HOME — not ambient overrides.
    assert "YOKE_ENV" not in env
    assert "YOKE_MACHINE_CONFIG_FILE" not in env
    assert env["YOKE_MACHINE_HOME"] == str(tmp_path / "home" / ".yoke")
    assert env["PATH"].startswith(str(tmp_path / "venv" / "bin"))
