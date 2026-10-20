"""Every Codex config writer shares one atomic read/modify/write boundary."""

from __future__ import annotations

import json
import multiprocessing
import os
import stat
import threading
import tomllib

import pytest

from yoke_contracts import codex_hook_trust_toml as storage


def _write(kind, config, checkout, entered, finished, release=None):
    """Run a real public writer with only disposable profile/ledger state."""
    from yoke_contracts import codex_config_posture, harness_settings_ledger
    from yoke_contracts.codex_hook_trust_store import mint_installed_checkout_trust
    from yoke_contracts.codex_posture_install import configure_codex_unattended_posture
    from yoke_contracts.harness_folder_trust_grant import grant_folder_trust
    from yoke_contracts.harness_settings_revert import revert_recorded

    os.environ["YOKE_MACHINE_HOME"] = str(config.parent / f"machine-{os.getpid()}")
    if release is not None:
        original = codex_config_posture.plan

        def held_plan(*args):
            result = original(*args)
            entered.set()
            if not release.wait(15):
                raise RuntimeError("configuration test did not release its writer")
            return result

        codex_config_posture.plan = held_plan
    else:
        entered.set()
    if kind == "folder":
        grant_folder_trust(
            checkout,
            codex_config=config,
            claude_state=config.parent / "absent-claude.json",
            cursor_file=config.parent / "absent-cursor/projects/trust.json",
        )
    elif kind == "posture":
        configure_codex_unattended_posture(checkout=checkout, config_path=config)
    elif kind == "hooks":
        mint_installed_checkout_trust(checkout, config_path=config)
    else:
        entry = harness_settings_ledger.codex_key_entry(
            config, "sandbox_mode", "danger-full-access"
        )
        assert harness_settings_ledger.record(entry) is None
        _, failures = revert_recorded()
        assert failures == []
    finished.set()


def _stop(processes, release):
    release.set()
    for process in processes:
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)


@pytest.mark.parametrize("kind", ["folder", "posture", "hooks", "revert"])
@pytest.mark.parametrize("alias", [False, True])
def test_public_writers_serialize_complete_updates(tmp_path, kind, alias):
    config = tmp_path / "config.toml"
    prefix = '# operator comment\nmodel = "chosen-model"\n'
    config.write_text(
        prefix + 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
    )
    config.chmod(0o600)
    selected = config
    if alias:
        selected = tmp_path / "alias.toml"
        selected.symlink_to(config)
    first_checkout, second_checkout = tmp_path / "first", tmp_path / "second"
    hooks = second_checkout / ".codex/hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "yoke hook evaluate SessionStart",
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    ctx = multiprocessing.get_context("spawn")
    held, started, first_done, second_done, release = [ctx.Event() for _ in range(5)]
    first = ctx.Process(
        target=_write,
        args=("folder", config, first_checkout, held, first_done, release),
    )
    second = ctx.Process(
        target=_write,
        args=(kind, selected, second_checkout, started, second_done),
    )
    processes = []
    stop_reading = threading.Event()
    invalid_reads = []

    def read_configs():
        while not stop_reading.is_set():
            try:
                document = tomllib.loads(config.read_text())
                assert document["model"] == "chosen-model"
            except (OSError, ValueError, KeyError, AssertionError) as exc:
                invalid_reads.append(type(exc).__name__)
            stop_reading.wait(0.002)

    reader = threading.Thread(target=read_configs)
    try:
        first.start()
        processes.append(first)
        assert held.wait(10)
        reader.start()
        second.start()
        processes.append(second)
        assert started.wait(10)
        assert not second_done.wait(0.5), "writer bypassed the held config transaction"
        release.set()
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        assert first_done.is_set() and second_done.is_set()
    finally:
        _stop(processes, release)
        stop_reading.set()
        if reader.ident is not None:
            reader.join(5)
    assert invalid_reads == []
    text = config.read_text()
    assert text.startswith(prefix)
    document = tomllib.loads(text)
    assert document["projects"][str(first_checkout)]["trust_level"] == "trusted"
    if kind in {"folder", "posture"}:
        assert document["projects"][str(second_checkout)]["trust_level"] == "trusted"
    elif kind == "hooks":
        assert any(str(hooks) in key for key in document["hooks"]["state"])
    else:
        assert "sandbox_mode" not in document
    if os.name != "nt":
        assert stat.S_IMODE(config.stat().st_mode) == 0o600
    if alias:
        assert selected.is_symlink()
    assert not list(tmp_path.glob(".config.toml.yoke-*"))


def test_invalid_input_and_invalid_planner_leave_original_untouched(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("not valid TOML")
    with pytest.raises(storage.CodexHookTrustStoreError, match="config.toml"):
        storage.mutate(config, lambda text, document: (text + "\n", None))
    assert config.read_text() == "not valid TOML"
    config.write_text('model = "keep"\n')
    with pytest.raises(storage.CodexHookTrustStoreError, match="invalid.*update"):
        storage.mutate(config, lambda text, document: ("invalid update", None))
    assert config.read_text() == 'model = "keep"\n'


def test_failed_publication_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('model = "keep"\n')

    def refuse(*args):
        raise OSError("simulated publication refusal")

    monkeypatch.setattr(storage.os, "replace", refuse)
    with pytest.raises(storage.CodexHookTrustStoreError, match="config.toml.*Recovery"):
        storage.mutate(
            config, lambda text, document: (text + 'extra = "value"\n', None)
        )
    assert config.read_text() == 'model = "keep"\n'
    assert not list(tmp_path.glob(".config.toml.yoke-*"))


def test_busy_alias_names_resolved_target_and_retry(tmp_path, monkeypatch):
    from filelock import FileLock

    config = tmp_path / "config.toml"
    config.write_text('model = "keep"\n')
    alias = tmp_path / "alias.toml"
    alias.symlink_to(config)
    monkeypatch.setattr(storage, "CONFIG_LOCK_TIMEOUT_SECONDS", 0.05)
    lock = FileLock(str(tmp_path / ".config.toml.yoke.lock"), mode=0o600)
    with lock:
        with pytest.raises(storage.CodexHookTrustStoreError) as caught:
            storage.mutate(alias, lambda text, document: (text + 'extra = "v"\n', None))
    message = str(caught.value)
    assert str(config) in message and "busy" in message
    assert "Recovery" in message and "retry" in message
    assert config.read_text() == 'model = "keep"\n'


def test_update_removes_its_lock_sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    config = tmp_path / "config.toml"
    storage.mutate(config, lambda text, document: ('model = "set"\n', None))
    assert config.read_text() == 'model = "set"\n'
    assert not (tmp_path / ".config.toml.yoke.lock").exists()
    assert not (tmp_path / "machine").exists()


def test_unremovable_lock_sidecar_is_recorded_for_uninstall(tmp_path, monkeypatch):
    from pathlib import Path

    from yoke_contracts import harness_settings_ledger

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    config = tmp_path / "config.toml"
    lock_path = tmp_path.resolve() / ".config.toml.yoke.lock"
    original_unlink = Path.unlink

    def keep_lock(self, *args, **kwargs):
        if self.name == lock_path.name:
            raise PermissionError("simulated unremovable lock")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", keep_lock)
    storage.mutate(config, lambda text, document: ('model = "set"\n', None))
    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert lock_path.exists()
    assert harness_settings_ledger.read() == [
        harness_settings_ledger.created_file_entry(lock_path)
    ]
