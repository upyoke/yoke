"""The embedded engine's MSVC runtime verdict follows where each DLL can come from."""

from __future__ import annotations

import ntpath

import pytest

from yoke_contracts import windows_preflight_facts as collector
from yoke_contracts import windows_vc_runtime
from yoke_contracts.embedded_postgres import engine_bin_dir
from yoke_contracts.windows_preflight import verdicts


pytestmark = pytest.mark.windows

_REAL_ISFILE = collector.os.path.isfile


@pytest.mark.parametrize(
    "source,local,severity",
    [
        ("system32", True, "info"),
        ("bin", True, "info"),
        ("redist", True, "info"),
        ("nowhere", True, "error"),
        ("nowhere", False, "warning"),
    ],
)
def test_vc_runtime_verdict_follows_each_dll_source(
    monkeypatch, tmp_path, source, local, severity
):
    system32 = ntpath.join("D:\\Win", "System32")
    bin_dir = engine_bin_dir(tmp_path)
    bin_dir.mkdir(parents=True)
    for name in windows_vc_runtime.RUNTIME_DLLS:
        if source == "bin":
            (bin_dir / name).write_bytes(b"dll")
    monkeypatch.setattr(
        collector.os.path,
        "isfile",
        lambda path: (source == "system32" and str(path).startswith(system32))
        or _REAL_ISFILE(path),
    )
    monkeypatch.setattr(
        windows_vc_runtime, "redist_reachable", lambda: source == "redist"
    )
    fact, missing = collector._vc_runtime({"SystemRoot": "D:\\Win"}, str(tmp_path))
    rows = verdicts(
        {"system": "Windows", "vc_runtime": fact, "vc_runtime_missing": missing},
        local=local,
    )
    result = next(r for r in rows if r["code"] == "windows_vc_runtime")
    assert result["severity"] == severity
    if source == "nowhere":
        assert missing == list(windows_vc_runtime.RUNTIME_DLLS)
        assert "msvcp140.dll" in result["message"]
        assert windows_vc_runtime.REDIST_HOST in result["message"]
    elif source == "redist":
        assert "installed into the engine bin" in result["message"]
    else:
        assert missing == [] and "present" in result["message"]
