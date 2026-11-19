"""OS scopes refuse invalid declarations and replace hand-written conditions."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

from runtime import os_scope_markers as scopes

pytestmark = pytest.mark.windows
ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path, source, platform=None):
    (tmp_path / "test_sample.py").write_text(source, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "from types import SimpleNamespace\nimport runtime.os_scope_markers as scopes\n"
        + (f"scopes.sys = SimpleNamespace(platform={platform!r})\n" if platform else ""),
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "runtime.os_scope_markers", "-rs", "-q"],
        cwd=tmp_path, env=env, text=True, capture_output=True,
    )


@pytest.mark.parametrize("declaration,error", [
    ('pytest.mark.posix_only', 'os_scope_reason_required'),
    ('pytest.mark.posix_only(reason=" ")', 'os_scope_reason_required'),
    ('pytest.mark.posix_only("a", reason="b")', 'os_scope_reason_required'),
    ('[pytest.mark.posix_only("a"), pytest.mark.linux_only("b")]', 'os_scope_conflict'),
    ('[pytest.mark.windows, pytest.mark.macos_only("a")]', 'os_scope_windows_conflict'),
])
def test_invalid_module_declaration_refuses_before_import(tmp_path, declaration, error):
    result = _run(tmp_path, f'import pytest\npytestmark = {declaration}\nraise RuntimeError("imported")\n')
    assert result.returncode != 0
    assert error in result.stdout + result.stderr
    assert 'RuntimeError: imported' not in result.stdout + result.stderr


@pytest.mark.parametrize("marker,platform,skipped", [
    ("posix_only", "win32", True), ("posix_only", "darwin", False),
    ("windows_only", "linux", True), ("windows_only", "win32", False),
    ("macos_only", "linux", True), ("macos_only", "darwin", False),
    ("linux_only", "darwin", True), ("linux_only", "linux", False),
])
def test_function_scope_selects_and_explains(tmp_path, marker, platform, skipped):
    result = _run(tmp_path, f'import pytest\n@pytest.mark.{marker}(reason="native API")\ndef test_x(): pass\n', platform)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ('1 skipped' if skipped else '1 passed') in result.stdout
    if skipped:
        assert f'{marker}: native API' in result.stdout


def test_module_scope_skips_before_unavailable_import(tmp_path):
    result = _run(tmp_path, 'import pytest\npytestmark = pytest.mark.windows_only("native API")\nimport absent_native_api\n', "linux")
    assert result.returncode == 5, result.stdout + result.stderr
    assert 'windows_only: native API' in result.stdout
    assert 'ModuleNotFoundError' not in result.stdout + result.stderr


@pytest.mark.parametrize("decorators,error", [
    ('@pytest.mark.linux_only()', 'os_scope_reason_required'),
    ('@pytest.mark.posix_only("a")\n@pytest.mark.macos_only("b")', 'os_scope_conflict'),
    ('@pytest.mark.windows\n@pytest.mark.linux_only("a")', 'os_scope_windows_conflict'),
])
def test_function_declarations_refuse(tmp_path, decorators, error):
    result = _run(tmp_path, f'import pytest\n{decorators}\ndef test_x(): pass\n')
    assert result.returncode != 0
    assert error in result.stdout + result.stderr


@pytest.mark.parametrize("source", [
    '@pytest.mark.skipif(os.name == "nt", reason="x")\ndef test_x(): pass',
    '@pytest.mark.xfail(sys.platform != "darwin", reason="x")\ndef test_x(): pass',
    '@pytest.mark.skipif("sys.platform == \'win32\'", reason="x")\ndef test_x(): pass',
    'if platform.system() == "Windows":\n pytest.skip("x")',
    '@pytest.mark.skipif(condition=sys.platform == "win32", reason="x")\ndef test_x(): pass',
    'if runtime.WINDOWS:\n pytest.xfail("x")',
    'IS_NATIVE = sys.platform == "linux"\nif IS_NATIVE:\n pytest.skip("x")',
    '@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="x")\ndef test_x(): pass',
    'if shutil.which("zsh") is None:\n pytest.skip("missing tool")',
    'from shutil import which as locate\nbash = locate("bash")\nif not bash:\n pytest.skip("missing")',
    '@pytest.mark.skipif(not shutil.which("git"), reason="x")\ndef test_x(): pass',
    'import pytest\npytest.importorskip("win32api")',
])
def test_scanner_finds_os_conditions(source):
    assert scopes.handwritten_os_skips(source)


@pytest.mark.parametrize("source", [
    '@pytest.mark.skipif(os.getuid() == 0, reason="root")\ndef test_x(): pass',
    '@pytest.mark.posix_only(reason="native API")\ndef test_x(): pass',
    'pytest.importorskip("opentelemetry.sdk")',
    'pytestmark = pytest.mark.skipif(not shutil.which("initdb"), reason="native suite provisions server")',
    'pytestmark = pytest.mark.macos_only("runs macOS zsh")\nif not shutil.which("zsh"):\n pytest.skip("missing")',
    '@pytest.mark.windows_only("native Windows API")\ndef test_x(): pytest.importorskip("win32api")',
])
def test_scanner_preserves_non_os_skips(source):
    assert scopes.handwritten_os_skips(source) == []


def test_no_handwritten_os_skips_remain():
    assert scopes.scan_tracked(ROOT) == []


def test_scanner_checks_only_tracked_runtime_and_test_python(tmp_path):
    for directory in ("runtime", "tests/nested", "other"):
        (tmp_path / directory).mkdir(parents=True)
        (tmp_path / directory / "test_native.py").write_text(
            'import pytest, sys\n@pytest.mark.skipif(sys.platform == "win32", reason="native")\ndef test_x(): pass\n'
        )
    (tmp_path / "tests/untracked.py").write_text('if WINDOWS: pytest.skip("native")\n')
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "add", "runtime", "tests/nested", "other"], cwd=tmp_path, check=True)
    assert scopes.scan_tracked(tmp_path) == [
        "runtime/test_native.py:2", "tests/nested/test_native.py:2",
    ]


def test_platform_simulation_preserves_interpreter_platform(tmp_path):
    simulated = "linux" if sys.platform == "win32" else "win32"
    result = _run(tmp_path,
                  f'import sys\ndef test_x(): assert sys.platform == {sys.platform!r}\n',
                  simulated)
    assert result.returncode == 0, result.stdout + result.stderr


def test_parameter_scopes_keep_portable_cases_active(tmp_path):
    source = '''import pytest
@pytest.mark.parametrize("operation", ["setup", pytest.param("upgrade", marks=pytest.mark.posix_only("host bundle"))])
@pytest.mark.parametrize("config,code", [({}, "missing"), (None, "unreadable")])
def test_x(operation, config, code): pass
'''
    result = _run(tmp_path, source, "win32")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed, 2 skipped" in result.stdout


def test_different_parameter_cases_can_own_different_os_scopes(tmp_path):
    source = '''import pytest
@pytest.mark.parametrize("value", [pytest.param("posix", marks=pytest.mark.posix_only("native")), pytest.param("windows", marks=pytest.mark.windows_only("native"))])
def test_x(value): pass
'''
    result = _run(tmp_path, source, "win32")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 1 skipped" in result.stdout


# Data-only /tmp literals the scanner reaches; each names what keeps it off disk.
TMP_DATA_LITERALS = {
    # Expected-value resolve() of the relay's machine-config path; nothing is written.
    ("runtime/api/cli/test_onboard_wizard_session_relay.py", "'/tmp/machine-config.json'"),
}


@pytest.mark.parametrize("source", [
    'import tempfile\ntempfile.TemporaryDirectory(dir="/tmp")',
    'open("/tmp/x", "w")',
    'from pathlib import Path\nPath("/tmp/x").write_text("data")',
    'import os\nos.makedirs(f"/tmp/{name}")',
    'from pathlib import Path\nLOCK = Path("/tmp") / "x.lock"\nLOCK.touch()',
])
def test_tmp_scanner_finds_real_paths(source):
    assert scopes.hardcoded_tmp_paths(source)


@pytest.mark.parametrize("source", [
    'expected = "/tmp/x"',
    'assert normalize("/tmp/x") == "/tmp/x"',
    'import os\nos.fspath("/tmp/x")',
    'import tempfile\ntempfile.TemporaryDirectory(dir=tmp_path)',
])
def test_tmp_scanner_preserves_data_literals(source):
    assert scopes.hardcoded_tmp_paths(source) == []


def test_no_hardcoded_tmp_paths_remain():
    hits = [f"{path}:{line} {literal}" for path, line, literal in scopes.scan_tracked_tmp_paths(ROOT)
            if (path, literal) not in TMP_DATA_LITERALS]
    assert hits == [], f"{scopes.TMP_PATH_FIX}:\n" + "\n".join(hits)
