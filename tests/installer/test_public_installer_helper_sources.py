"""Candidate installs prove credential-helper sources safe before activation."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

import pytest

from public_installer_helpers import load_installer
from yoke_cli.config import github_git_credential_bundle

BUNDLE_STUB = (
    "import os, stat\nfrom pathlib import Path\n"
    "import yoke_contracts.github_origin as origin\n"
    "MAX_HELPER_SOURCE_BYTES = 2 * 1024 * 1024\n"
    "class GitHubCredentialBundleError(RuntimeError):\n    pass\n"
    "def _bundle_sources():\n"
    "    return ((Path(origin.__file__), 'origin.py'), (Path(__file__), 'b.py'))\n"
    # The real guard, unchanged, so the fixture rejects exactly what releases do.
    + inspect.getsource(github_git_credential_bundle._safe_read_source)
)


def _wheel(directory: Path, name: str, files: dict[str, str], requires=()) -> None:
    stem = f"{name.replace('-', '_')}-1.0"
    meta = f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n" + "".join(
        f"Requires-Dist: {item}\n" for item in requires
    )
    files = {
        **files,
        f"{stem}.dist-info/METADATA": meta,
        f"{stem}.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: test\n"
        "Root-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = []
    with zipfile.ZipFile(directory / f"{stem}-py3-none-any.whl", "w") as archive:
        for path, text in files.items():
            data = text.encode()
            info = zipfile.ZipInfo(path)
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            record.append(f"{path},sha256={digest.decode().rstrip('=')},{len(data)}")
        record.append(f"{stem}.dist-info/RECORD,,")
        archive.writestr(f"{stem}.dist-info/RECORD", "\n".join(record) + "\n")


@pytest.fixture
def release(tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _wheel(
        wheels,
        "yoke-cli",
        {
            "yoke_cli/__init__.py": "",
            "yoke_cli/main.py": "def main():\n    print('1.0')\n",
            "yoke_cli/config/__init__.py": "",
            "yoke_cli/config/github_git_credential_bundle.py": BUNDLE_STUB,
            "yoke_cli/config/github_git_credential_launcher.py": "# launcher\n",
            "yoke_cli-1.0.dist-info/entry_points.txt": "[console_scripts]\n"
            "yoke = yoke_cli.main:main\n",
        },
        requires=("yoke-contracts==1.0", "third-party-pkg==1.0"),
    )
    _wheel(wheels, "yoke-contracts", {"yoke_contracts/__init__.py": "", "yoke_contracts/github_origin.py": "ORIGIN = 1\n"})
    _wheel(wheels, "third-party-pkg", {"third_party_pkg/__init__.py": "VALUE = 1\n"})
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("UV_")
    }
    env.update(UV_CACHE_DIR=str(tmp_path / "cache"), UV_PYTHON_DOWNLOADS="never")
    command = [
        "uv", "tool", "install", "yoke-cli==1.0", "--python", sys.executable,
        "--reinstall", "--force", "--no-index", "--find-links", str(wheels),
    ]
    return tmp_path, command, env


def _generation(root: Path, name: str, env: dict[str, str]):
    generation = root / "releases" / name
    generation.mkdir(parents=True)
    tools = dict(env, UV_TOOL_DIR=str(generation / "tools"), UV_TOOL_BIN_DIR=str(generation / "bin"))
    return generation, tools


def _helper_modes(generation: Path) -> dict[str, int]:
    site = next((generation / "tools/yoke-cli/lib").glob("python*/site-packages"))
    return {
        path.name: stat.S_IMODE(path.stat().st_mode)
        for path in (
            site / "yoke_contracts/github_origin.py",
            site / "yoke_cli/config/github_git_credential_bundle.py",
            site / "yoke_cli/config/github_git_credential_launcher.py",
        )
    }


def _cached(cache: Path, name: str) -> Path:
    return next(path for path in cache.rglob(name) if "archive" in str(path))


@pytest.fixture
def permissive_umask():
    previous = os.umask(0o002)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.fixture
def uv_calls(monkeypatch):
    calls: list[tuple[list[str], dict]] = []
    real = subprocess.run

    def run(command, **kwargs):
        calls.append((list(command), kwargs))
        return real(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def _cleans(calls) -> list[list[str]]:
    return [command for command, _ in calls if command[:3] == ["uv", "cache", "clean"]]


def test_check_covers_every_bundle_source_and_launcher():
    installer = load_installer()
    result = subprocess.run(
        [sys.executable, "-c", installer.HELPER_SOURCE_CHECK],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)["checked"] == 19
    assert len(github_git_credential_bundle._bundle_sources()) + 1 == 19


def test_permissive_parent_umask_installs_safe_helpers_and_reuses_warm_cache(
    release, permissive_umask, uv_calls, capsys
):
    installer = load_installer()
    root, command, env = release
    first, tools = _generation(root, "first", env)
    assert installer._install_qualified_candidate(command, tools, first).returncode == 0
    assert set(_helper_modes(first).values()) == {0o644}
    assert os.umask(0o002) == 0o002, "the parent umask must stay unchanged"
    cached = _cached(root / "cache", "github_origin.py").stat().st_ino
    second, tools = _generation(root, "second", env)
    assert installer._install_qualified_candidate(command, tools, second).returncode == 0
    assert _cached(root / "cache", "github_origin.py").stat().st_ino == cached
    assert set(_helper_modes(second).values()) == {0o644}
    assert _cleans(uv_calls) == []
    assert "helper_source_cache_repaired" not in capsys.readouterr().err
    installs = [kwargs for command_, kwargs in uv_calls if command_ == command]
    assert [kwargs["umask"] for kwargs in installs] == [0o022, 0o022]


def test_group_writable_cached_helpers_are_evicted_once_and_reinstalled(
    release, uv_calls, capsys
):
    installer = load_installer()
    root, command, env = release
    seeded, tools = _generation(root, "seeded", env)
    subprocess.run(command, env=tools, check=True, capture_output=True, umask=0o002)
    assert 0o664 in _helper_modes(seeded).values()
    unrelated = _cached(root / "cache", "third_party_pkg")
    unrelated_inode = unrelated.stat().st_ino
    candidate, tools = _generation(root, "candidate", env)
    config = root / "uv.toml"
    config.write_text("")
    configured = [*command, "--config-file", str(config)]
    result = installer._install_qualified_candidate(configured, tools, candidate)
    assert result.returncode == 0, result.stderr
    assert set(_helper_modes(candidate).values()) == {0o644}
    assert _cleans(uv_calls) == [
        ["uv", "cache", "clean", "yoke-cli", "yoke-contracts", "--config-file", str(config)]
    ]
    clean_kwargs = next(kw for cmd, kw in uv_calls if cmd[:3] == ["uv", "cache", "clean"])
    assert clean_kwargs["env"] == tools
    assert unrelated.stat().st_ino == unrelated_inode
    assert "helper_source_cache_repaired" in capsys.readouterr().err
    verdict = subprocess.run(
        [str(candidate / "tools/yoke-cli/bin/python3"), "-I", "-c", installer.HELPER_SOURCE_CHECK],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(verdict.stdout) == {"checked": 3, "unsafe_permissions": [], "refusal": None}


def _scripted(monkeypatch, installer, *, verdicts, clean=0, retry=0):
    calls: list[list[str]] = []
    queue = list(verdicts)

    def run(command, **kwargs):
        calls.append(list(command))
        if command[:3] == ["uv", "cache", "clean"]:
            return subprocess.CompletedProcess(command, clean, "", "cache locked")
        if command[:3] == ["uv", "tool", "install"]:
            installs = sum(1 for call in calls if call[:3] == ["uv", "tool", "install"])
            code = retry if installs > 1 else 0
            return subprocess.CompletedProcess(command, code, "", "install failed")
        return subprocess.CompletedProcess(command, 0, queue.pop(0), "")

    monkeypatch.setattr(installer.subprocess, "run", run)
    return calls


def _verdict(loose=(), refusal=None) -> str:
    return json.dumps({"checked": 19, "unsafe_permissions": list(loose), "refusal": refusal})


COMMAND = ["uv", "tool", "install", "yoke-cli==1.0"]


def test_repeated_unsafe_permissions_refuse_after_one_cleanup(monkeypatch, tmp_path):
    installer = load_installer()
    calls = _scripted(monkeypatch, installer, verdicts=[_verdict(["a"]), _verdict(["a"])])
    with pytest.raises(installer.InstallError, match="helper_source_permissions_unsafe"):
        installer._install_qualified_candidate(COMMAND, {}, tmp_path)
    assert sum(call[:3] == ["uv", "cache", "clean"] for call in calls) == 1
    assert sum(call == COMMAND for call in calls) == 2


@pytest.mark.parametrize(
    ("verdict", "code"),
    [
        (_verdict(["a"], refusal="/x: GitHub helper bundle source is unsafe"), "helper_source_unsafe"),
        ("not json", "helper_source_check_failed"),
    ],
)
def test_other_check_failures_refuse_without_cache_cleanup(monkeypatch, tmp_path, verdict, code):
    installer = load_installer()
    calls = _scripted(monkeypatch, installer, verdicts=[verdict])
    with pytest.raises(installer.InstallError, match=code):
        installer._install_qualified_candidate(COMMAND, {}, tmp_path)
    assert not any(call[:3] == ["uv", "cache", "clean"] for call in calls)


def test_cache_cleanup_failure_refuses_without_reinstall(monkeypatch, tmp_path):
    installer = load_installer()
    calls = _scripted(monkeypatch, installer, verdicts=[_verdict(["a"])], clean=2)
    with pytest.raises(installer.InstallError, match="helper_source_cache_clean_failed.*cache locked"):
        installer._install_qualified_candidate(COMMAND, {}, tmp_path)
    assert sum(call == COMMAND for call in calls) == 1


def test_reinstall_failure_removes_candidate_and_never_activates(monkeypatch, tmp_path):
    installer = load_installer()
    calls = _scripted(monkeypatch, installer, verdicts=[_verdict(["a"])], retry=1)
    generation = tmp_path / "releases" / "candidate"
    generation.mkdir(parents=True)
    result = installer._install_candidate(COMMAND, {}, tmp_path, generation, "1.0")
    assert result.returncode == 1
    assert not generation.exists()
    assert not any("runtime.py" in " ".join(call) for call in calls)


def test_unsafe_candidate_is_removed_before_activation(monkeypatch, tmp_path):
    installer = load_installer()
    calls = _scripted(monkeypatch, installer, verdicts=[_verdict(refusal="/x: unsafe")])
    generation = tmp_path / "releases" / "candidate"
    generation.mkdir(parents=True)
    with pytest.raises(installer.InstallError, match="helper_source_unsafe"):
        installer._install_candidate(COMMAND, {}, tmp_path, generation, "1.0")
    assert not generation.exists()
    assert not any("runtime.py" in " ".join(call) for call in calls)
