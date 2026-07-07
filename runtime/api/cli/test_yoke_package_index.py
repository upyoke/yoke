"""PEP 503 index contract proof for the installable Yoke product client."""

from __future__ import annotations

import json
import os
import re
import subprocess
from yoke_core.tools.build_release import create_seeded_pip_venv
import zipfile
from pathlib import Path
from urllib.parse import quote

from yoke_core.tools import distribution_publish, package_index, release_artifacts


REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
_LINK_RE = re.compile(r'<a\s+href=["\'](?P<href>[^"\']+)["\']\s*>')


def test_pep503_simple_index_and_clean_venv_install(
    tmp_path: Path,
    product_wheelhouse: Path,
) -> None:
    index_dir = tmp_path / "simple"
    wheel_base_url = "https://api.upyoke.com/dist/releases/0.2.0/wheels"

    by_project = package_index.generate_index(
        wheel_dir=product_wheelhouse,
        index_dir=index_dir,
        wheel_base_url=wheel_base_url,
    )

    # Only the product projects are listed; no third-party closure.
    assert set(by_project) == {
        "yoke-contracts",
        "yoke-cli",
        "yoke-harness",
        "yoke-core",
    }
    root_html = (index_dir / "index.html").read_text(encoding="utf-8")
    for project in by_project:
        assert f'href="{project}/"' in root_html

    # Each per-project page links exactly its wheel(s) with a #sha256= fragment
    # pointing at the immutable versioned wheel URL.
    product_records = {
        record.project_name: record
        for record in package_index.read_wheel_records(product_wheelhouse)
        if record.canonical_name in package_index.PRODUCT_PACKAGE_NAMES
    }
    for project, record in product_records.items():
        project_html = (index_dir / project / "index.html").read_text(encoding="utf-8")
        hrefs = [match.group("href") for match in _LINK_RE.finditer(project_html)]
        assert hrefs, project
        url, _, sha = hrefs[0].partition("#sha256=")
        # The wheel filename is URL-quoted in the link (local versions carry '+').
        assert url == f"{wheel_base_url}/{quote(record.filename, safe='%')}"
        assert sha == record.sha256

    venv_dir = tmp_path / "clean-venv"
    create_seeded_pip_venv(venv_dir)
    venv_python = venv_dir / "bin" / "python"
    yoke = venv_dir / "bin" / "yoke"
    # The published index links remote wheels; the offline clean-venv proof
    # installs from the local closure (the same wheels plus third-party deps).
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(product_wheelhouse),
            "yoke-cli",
            "yoke-harness",
            "yoke-core",
        ],
        cwd=tmp_path,
        timeout=180,
    )
    assert yoke.is_file()

    external_project = tmp_path / "external-project"
    machine_home = tmp_path / "home" / ".yoke"
    external_project.mkdir()
    machine_home.mkdir(parents=True)
    env = _product_env(machine_home=machine_home, venv_dir=venv_dir)
    # The engine and its DB driver ship on the channel and install alongside
    # the client; the repo control plane does not.
    _assert_module_presence(
        venv_python,
        external_project,
        env,
        present=("yoke_core", "psycopg"),
        absent=("runtime",),
    )
    assert _run(
        [str(yoke), "--version"], cwd=external_project, env=env,
    ).stdout.strip() == product_records["yoke-cli"].version
    help_result = _run([str(yoke), "--help"], cwd=external_project, env=env)
    assert "yoke status" in help_result.stdout


def test_distribution_publish_validates_release_and_writes_channel(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / "0.2.0"
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    records, wheel_records = _sample_release(wheels_dir)
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n", encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url="https://api.upyoke.com/dist/releases/0.2.0/wheels",
    )

    assert distribution_publish.validate_release_directory(release_dir) == records

    channel = distribution_publish.channel_payload(
        channel="stable",
        version="0.2.0",
        index_url="https://api.upyoke.com/simple/",
        release_base_url="https://api.upyoke.com/dist/releases/0.2.0",
        generated_at="2026-06-18T00:00:00+00:00",
    )
    assert channel["schema_version"] == 2
    assert channel["channel"] == "stable"
    assert channel["version"] == "0.2.0"
    assert channel["index_url"] == "https://api.upyoke.com/simple/"
    assert channel["installer"]["python_url"] == (
        "https://api.upyoke.com/dist/install.py"
    )
    assert channel["installer"]["shell_url"] == "https://api.upyoke.com/install"

    checks = distribution_publish.build_url_checks(
        base_url="https://api.upyoke.com/dist/releases/0.2.0/",
        records=records,
        index_url="https://api.upyoke.com/simple/",
        include_mutable=True,
        mutable_channel="stable",
    )
    urls = {check.url: check for check in checks}
    # Root + per-project simple pages are mutable; wheels are immutable.
    assert urls["https://api.upyoke.com/simple/"].cache_control_contains == "max-age=60"
    assert (
        urls["https://api.upyoke.com/simple/yoke-cli/"].cache_control_contains
        == "max-age=60"
    )
    wheel_url = (
        "https://api.upyoke.com/dist/releases/0.2.0/wheels/"
        "yoke_cli-0.2.0-py3-none-any.whl"
    )
    assert urls[wheel_url].cache_control_contains == "immutable"
    assert urls[wheel_url].sha256 == _record(records, "yoke-cli")["sha256"]
    assert urls[wheel_url].size == _record(records, "yoke-cli")["size"]
    assert "https://api.upyoke.com/dist/channels/stable.json" in urls
    assert "https://api.upyoke.com/dist/channels/latest.json" not in urls
    assert "https://api.upyoke.com/install" in urls


def test_distribution_publish_rejects_simple_index_hash_drift(tmp_path: Path) -> None:
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / "0.2.0"
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    records, wheel_records = _sample_release(wheels_dir)
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n", encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url="https://api.upyoke.com/dist/releases/0.2.0/wheels",
    )
    # Corrupt one wheel's bytes (size-preserving) after the index was rendered.
    target = next(wheels_dir.glob("yoke_cli-*.whl"))
    original = target.read_bytes()
    target.write_bytes(b"\x00" * len(original))

    try:
        distribution_publish.validate_release_directory(release_dir)
    except ValueError as exc:
        assert "sha256" in str(exc)
    else:
        raise AssertionError("validate-release must reject hash drift")


def test_validate_release_matches_url_quoted_local_version_links(
    tmp_path: Path,
) -> None:
    # Local versions carry '+', which is URL-quoted in the simple-index link;
    # validate-release must unquote to match the on-disk wheel filename.
    version = "0.2.0+gabc123"
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / version
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    records, wheel_records = _sample_release(wheels_dir, version=version)
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n", encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url=f"https://api.upyoke.com/dist/releases/{version}/wheels",
    )

    assert distribution_publish.validate_release_directory(release_dir) == records


def _sample_release(
    wheels_dir: Path,
    *,
    version: str = "0.2.0",
) -> tuple[list[dict[str, object]], list[package_index.WheelRecord]]:
    for name in package_index.PRODUCT_PACKAGE_NAMES:
        dist = name.replace("-", "_")
        metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        with zipfile.ZipFile(
            wheels_dir / f"{dist}-{version}-py3-none-any.whl", "w"
        ) as archive:
            archive.writestr(f"{dist}-{version}.dist-info/METADATA", metadata)
    wheel_records = package_index.read_wheel_records(wheels_dir)
    records = package_index.build_records_manifest(wheel_records)
    return records, wheel_records


def _record(records: list[dict[str, object]], project: str) -> dict[str, object]:
    return next(entry for entry in records if entry["project"] == project)


def _product_env(*, machine_home: Path, venv_dir: Path) -> dict[str, str]:
    return {
        "HOME": str(machine_home.parent),
        "PATH": f"{venv_dir / 'bin'}:{BASE_PATH}",
        "YOKE_MACHINE_HOME": str(machine_home),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def _assert_module_presence(
    python: Path,
    cwd: Path,
    env: dict[str, str],
    *,
    present: tuple[str, ...],
    absent: tuple[str, ...],
) -> None:
    code = (
        "import importlib.util; "
        f"missing = [name for name in {present!r} "
        "if importlib.util.find_spec(name) is None]; "
        "assert not missing, ('missing', missing); "
        f"unexpected = [name for name in {absent!r} "
        "if importlib.util.find_spec(name) is not None]; "
        "assert not unexpected, ('unexpected', unexpected)"
    )
    _run([str(python), "-c", code], cwd=cwd, env=env)


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env) if env is not None else os.environ.copy()
    run_env.pop("PYTHONPATH", None)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check:
        assert result.returncode == 0, _format_result(result)
    return result


def _format_result(result: subprocess.CompletedProcess[str]) -> str:
    return (
        f"command failed with {result.returncode}: {result.args!r}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
