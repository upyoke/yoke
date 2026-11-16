"""Persistent Windows PATH reporting, repair and ownership on uninstall."""

import sys
from types import SimpleNamespace

from yoke_contracts import shell_path_state, windows_user_path


class RegistryKey:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def registry(monkeypatch, value):
    state = {"value": value, "kind": 2, "writes": []}

    def write(_handle, _name, _reserved, kind, updated):
        state.update(value=updated, kind=kind)
        state["writes"].append(updated)

    fake = SimpleNamespace(
        HKEY_CURRENT_USER=1,
        HKEY_LOCAL_MACHINE=2,
        REG_EXPAND_SZ=2,
        KEY_READ=1,
        KEY_WRITE=2,
        OpenKey=lambda *_: RegistryKey(),
        CreateKeyEx=lambda *_: RegistryKey(),
        QueryValueEx=lambda *_: (state["value"], state["kind"]),
        SetValueEx=write,
        ExpandEnvironmentStrings=lambda value: value,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    import ctypes

    def broadcast(*_):
        return 1

    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(user32=SimpleNamespace(SendMessageTimeoutW=broadcast)),
        raising=False,
    )
    return state


def test_uv_owned_user_path_is_case_insensitive_and_not_removed(monkeypatch):
    state = registry(monkeypatch, r"%USERPROFILE%\.local\bin;C:\Other")
    env = {"USERPROFILE": r"C:\Users\Ada", "HOME": r"C:\Users\Ada"}
    directory = "c:\\users\\ada\\.local\\BIN\\"
    assert windows_user_path.contains(
        windows_user_path.read_user_path(), directory, env
    )
    assert windows_user_path.write_user_path(directory, env) == []
    monkeypatch.setattr(sys, "platform", "win32")
    assert shell_path_state.remove_shell_path(env=env) == []
    assert not state["writes"]


def test_user_path_repair_preserves_other_entries_and_registry_type(monkeypatch):
    state = registry(monkeypatch, r"%USERPROFILE%\custom;C:\Other")
    assert windows_user_path.write_user_path(r"C:\Tools\uv", {}) == [
        windows_user_path.USER_PATH_LOCATION
    ]
    assert state["value"] == r"%USERPROFILE%\custom;C:\Other;C:\Tools\uv"
    assert state["kind"] == 2


def test_status_and_doctor_report_user_path_without_posix_shells(monkeypatch, tmp_path):
    from yoke_cli.config import path_doctor, path_windows

    registry(monkeypatch, str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(path_windows, "fresh_path", lambda _: str(tmp_path))
    monkeypatch.setattr(
        path_windows.shutil,
        "which",
        lambda tool, **_: str(tmp_path / (tool + ".cmd")) if tool == "yoke" else None,
    )
    diagnosis = path_doctor.diagnose(
        env={"HOME": str(tmp_path), "UV_TOOL_BIN_DIR": str(tmp_path), "PATH": ""}
    )
    assert diagnosis.startup_file == windows_user_path.USER_PATH_LOCATION
    assert diagnosis.future_adds_bin
    assert not diagnosis.current_on_path
    assert not diagnosis.needs_fix
    assert diagnosis.contexts[0]["path"] == str(tmp_path)
    contract = shell_path_state.resolve_path_state_contract(env={"HOME": str(tmp_path)})
    assert contract.yoke_bin.endswith("yoke.cmd")
    assert contract.supported_startup_files == ()


def test_status_runtime_reports_persistent_path(monkeypatch):
    from yoke_cli.config import status_runtime, status_render

    state = registry(monkeypatch, r"C:\Tools\uv;C:\Other")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("UV_TOOL_BIN_DIR", r"C:\Tools\uv")
    monkeypatch.setattr(status_runtime.shutil, "which", lambda _: r"C:\Tools\uv\yoke.cmd")
    monkeypatch.setattr(
        status_runtime.install_binding, "detect", lambda: {"kind": "packaged_wheel"}
    )
    runtime = status_runtime.build_runtime_status(
        {},
        required_imports=(),
        runtime_packages=(),
        import_status=lambda _: {},
        package_version=lambda *args, **kwargs: "1.0",
        issue=lambda *args: {},
    )
    assert runtime["user_path"]["value"] == state["value"]
    assert runtime["user_path"]["contains_tool_bin"]
    text = status_render.render_human({"runtime": runtime})
    assert windows_user_path.USER_PATH_LOCATION in text
    assert state["value"] in text
