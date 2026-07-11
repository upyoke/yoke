"""PEP 503 index contract proof for the installable Yoke product client."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest

from yoke_core.tools import distribution_publish, package_index, release_artifacts
from yoke_core.tools.build_release import create_seeded_pip_venv


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


def test_validate_release_rejects_version_without_local_segment(
    tmp_path: Path,
) -> None:
    version = "0.2.0"
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

    with pytest.raises(ValueError, match="PEP 440 local segment"):
        distribution_publish.validate_release_directory(release_dir)


def test_validate_release_rejects_unpinned_sibling(tmp_path: Path) -> None:
    # A product wheel whose sibling Requires-Dist is bare (unpinned) would let a
    # pip-based install resolve a same-named public-index package; validation
    # must fail closed on it.
    version = "0.2.0+gabc123"
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / version
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    records, wheel_records = _sample_release(
        wheels_dir, version=version, sibling_specifier=""
    )
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n", encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url=f"https://api.upyoke.com/dist/releases/{version}/wheels",
    )

    try:
        distribution_publish.validate_release_directory(release_dir)
    except ValueError as exc:
        assert f"pinned to =={version}" in str(exc)
    else:
        raise AssertionError("validate-release must reject an unpinned sibling")


def test_validate_release_rejects_manifest_version_drift(tmp_path: Path) -> None:
    version = "0.2.0+gabc123"
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / version
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    records, wheel_records = _sample_release(wheels_dir, version=version)
    for record in records:
        record["version"] = "0.2.0+different"
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n", encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url=f"https://api.upyoke.com/dist/releases/{version}/wheels",
    )

    with pytest.raises(ValueError, match="does not match wheel metadata"):
        distribution_publish.validate_release_directory(release_dir)


def test_validate_release_rejects_invalid_wheel_record(tmp_path: Path) -> None:
    version = "0.2.0+gabc123"
    output_root = tmp_path / "release"
    release_dir = output_root / "dist" / "releases" / version
    wheels_dir = release_dir / "wheels"
    simple_dir = output_root / "simple"
    wheels_dir.mkdir(parents=True)

    _, _ = _sample_release(wheels_dir, version=version)
    core = next(wheels_dir.glob("yoke_core-*.whl"))
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(core, "a") as archive:
            wheel_arcname = next(
                name for name in archive.namelist()
                if name.endswith(".dist-info/WHEEL")
            )
            archive.writestr(wheel_arcname, archive.read(wheel_arcname))
    wheel_records = package_index.read_wheel_records(wheels_dir)
    records = package_index.build_records_manifest(wheel_records)
    (release_dir / release_artifacts.RELEASE_RECORDS_FILENAME).write_text(
        json.dumps(records, indent=2) + "\n", encoding="utf-8",
    )
    package_index.write_simple_index(
        index_dir=simple_dir,
        records=wheel_records,
        wheel_base_url=f"https://api.upyoke.com/dist/releases/{version}/wheels",
    )

    with pytest.raises(ValueError, match="duplicate archive member"):
        distribution_publish.validate_release_directory(release_dir)


def _sample_release(
    wheels_dir: Path,
    *,
    version: str = "0.2.0",
    sibling_specifier: str | None = None,
) -> tuple[list[dict[str, object]], list[package_index.WheelRecord]]:
    """Write the four product wheels with exact-pinned sibling Requires-Dist.

    ``sibling_specifier`` overrides the ``==<version>`` pin for every sibling
    line (e.g. ``""`` for a bare, unpinned entry) so the failure path can be
    exercised.
    """

    specifier = f"=={version}" if sibling_specifier is None else sibling_specifier
    for name in package_index.PRODUCT_PACKAGE_NAMES:
        dist = name.replace("-", "_")
        lines = [
            "Metadata-Version: 2.1",
            f"Name: {name}",
            f"Version: {version}",
        ]
        lines += [
            f"Requires-Dist: {dep}{specifier}"
            for dep in package_index.PRODUCT_SIBLING_DEPENDENCIES[name]
        ]
        metadata = ("\n".join(lines) + "\n").encode("utf-8")
        wheel_metadata = (
            b"Wheel-Version: 1.0\nGenerator: test\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        )
        dist_info = f"{dist}-{version}.dist-info"
        files = {
            f"{dist_info}/METADATA": metadata,
            f"{dist_info}/WHEEL": wheel_metadata,
        }
        record_arcname = f"{dist_info}/RECORD"
        record_lines = [
            f"{arcname},{_wheel_record_hash(data)},{len(data)}"
            for arcname, data in files.items()
        ]
        record_lines.append(f"{record_arcname},,")
        files[record_arcname] = (
            "\n".join(record_lines) + "\n"
        ).encode("utf-8")
        with zipfile.ZipFile(
            wheels_dir / f"{dist}-{version}-py3-none-any.whl", "w"
        ) as archive:
            for arcname, data in files.items():
                archive.writestr(arcname, data)
    wheel_records = package_index.read_wheel_records(wheels_dir)
    records = package_index.build_records_manifest(wheel_records)
    return records, wheel_records


def _wheel_record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}"


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
