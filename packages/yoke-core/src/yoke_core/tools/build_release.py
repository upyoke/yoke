"""Build the public Yoke product release artifact tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL

from yoke_core.tools import (
    package_index,
    product_release_version,
    wheel_sibling_pins,
)
from yoke_core.tools.release_artifacts import (
    INSTALLER_ASSET_DIR,
    ReleaseBuild,
    ReleaseBuildError,
    materialize_release_artifacts,
)


PRODUCT_PACKAGE_NAMES = package_index.PRODUCT_PACKAGE_NAMES
BOOTSTRAP_REQUIREMENTS = ("pip>=23.1",)


def build_release(
    *,
    repo_root: Path,
    output_root: Path,
    base_url: str,
    channel: str = "latest",
    generated_at: str | None = None,
    uv_executable: str | None = None,
    python_executable: str | None = None,
    installer_asset_dir: Path | None = None,
) -> ReleaseBuild:
    """Build the product wheels and render the hosted release directory.

    The product wheels are pure-python ``py3-none-any`` artifacts, so the PEP 503
    index hosts a single wheel per project with no per-platform split. Third-party
    dependencies are resolved from PyPI at install time and are never hosted here.
    """

    repo_root = repo_root.resolve()
    output_root = output_root.resolve()
    generated_at = generated_at or _utc_now()
    if output_root.exists():
        shutil.rmtree(output_root)
    wheelhouse = output_root / "_build" / "wheelhouse"
    build_product_wheelhouse(
        repo_root=repo_root,
        wheelhouse=wheelhouse,
        uv_executable=uv_executable,
        python_executable=python_executable,
    )
    records = package_index.read_wheel_records(wheelhouse)
    package_index.validate_records(records)
    product_records = [
        record
        for record in records
        if record.canonical_name in PRODUCT_PACKAGE_NAMES
    ]
    version = _shared_product_version(product_records)
    asset_dir = (
        installer_asset_dir
        if installer_asset_dir is not None
        else repo_root / INSTALLER_ASSET_DIR
    )
    return materialize_release_artifacts(
        records=product_records,
        output_root=output_root,
        version=version,
        channel=channel,
        base_url=base_url,
        generated_at=generated_at,
        installer_asset_dir=asset_dir,
    )


def build_product_wheelhouse(
    *,
    repo_root: Path,
    wheelhouse: Path,
    uv_executable: str | None = None,
    python_executable: str | None = None,
) -> Path:
    """Build product wheels with uv and fill their dependency wheel closure.

    The closure (product wheels plus their third-party dependency wheels) is the
    offline-install surface used by clean-venv proof tests. The published PEP 503
    index hosts only the product wheels; the closure is not published.
    """

    repo_root = repo_root.resolve()
    wheelhouse = wheelhouse.resolve()
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir(parents=True)
    uv = _uv_executable(uv_executable)
    for package_name in PRODUCT_PACKAGE_NAMES:
        _run(
            [
                uv,
                "build",
                "--wheel",
                "--package",
                package_name,
                "--out-dir",
                str(wheelhouse),
                "--directory",
                str(repo_root),
                "--no-progress",
            ],
            cwd=repo_root,
        )
    # Pin product-sibling Requires-Dist to the shared lockstep version before the
    # third-party closure step reads the wheels from disk. Bare siblings would let
    # a pip-based install resolve a same-named public-index package; exact pins
    # constrain resolution to the real channel wheels.
    version = wheel_sibling_pins.pin_wheelhouse_product_siblings(
        wheelhouse, PRODUCT_PACKAGE_NAMES
    )
    # Fail before pip consults the public index. Without a local segment, a
    # same-version public wheel can outrank the channel wheel by build tag.
    product_release_version.assert_public_index_unforgeable(version)
    requirements = [
        f"{record.name}=={record.version}"
        for record in package_index.read_wheel_records(wheelhouse)
        if record.canonical_name in PRODUCT_PACKAGE_NAMES
    ]
    with _pip_python(python_executable) as python:
        _run(
            [
                str(python),
                "-m",
                "pip",
                "wheel",
                "--wheel-dir",
                str(wheelhouse),
                "--find-links",
                str(wheelhouse),
                *requirements,
                *BOOTSTRAP_REQUIREMENTS,
            ],
            cwd=repo_root,
        )
    package_index.validate_records(package_index.read_wheel_records(wheelhouse))
    return wheelhouse


def _shared_product_version(records: Sequence[package_index.WheelRecord]) -> str:
    versions = {
        record.version
        for record in records
        if record.canonical_name in PRODUCT_PACKAGE_NAMES
    }
    if len(versions) != 1:
        raise ReleaseBuildError(
            "product wheels must share one version: " + ", ".join(sorted(versions))
        )
    return versions.pop()


def _uv_executable(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_value = os.environ.get("YOKE_UV")
    if env_value:
        return env_value
    found = shutil.which("uv")
    if found:
        return found
    raise ReleaseBuildError(
        "uv is required to build Yoke product wheels; install uv or set YOKE_UV"
    )


class _pip_python:
    def __init__(self, explicit: str | None) -> None:
        self._explicit = explicit
        self._tmp: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        if self._explicit:
            return Path(self._explicit)
        self._tmp = tempfile.TemporaryDirectory(prefix="yoke-pip-wheel-")
        root = Path(self._tmp.name)
        create_seeded_pip_venv(root)
        return root / "bin" / "python"

    def __exit__(self, *exc: object) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()


def create_seeded_pip_venv(
    root: Path, *, system_site_packages: bool = False
) -> None:
    """Create a venv with pip seeded into it.

    Prefers ``uv venv --seed``: the stdlib venv's ensurepip bootstrap fails on
    some setup-python interpreters (notably 3.10 on the self-hosted CI runner),
    while uv seeds pip/setuptools/wheel without ensurepip. Falls back to the
    stdlib builder when uv is unavailable.
    """
    uv = shutil.which("uv")
    if uv is not None:
        args = [uv, "venv", "--seed", "--python", sys.executable]
        if system_site_packages:
            args.append("--system-site-packages")
        args.append(str(root))
        completed = subprocess.run(
            args, text=True, capture_output=True, check=False
        )
        if completed.returncode == 0:
            return
    venv.EnvBuilder(
        with_pip=True, system_site_packages=system_site_packages
    ).create(root)


def _run(command: Sequence[str], *, cwd: Path) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=600,
    )
    if completed.returncode != 0:
        raise ReleaseBuildError(
            f"command failed with {completed.returncode}: {list(command)!r}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build Yoke product release artifacts.",
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--base-url", default=DISTRIBUTION_PROD_URL)
    parser.add_argument("--channel", default="latest")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--uv", dest="uv_executable", default=None)
    parser.add_argument("--python", dest="python_executable", default=None)
    parser.add_argument("--installer-asset-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="json_mode")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = build_release(
            repo_root=args.repo_root,
            output_root=args.output_root,
            base_url=args.base_url,
            channel=args.channel,
            generated_at=args.generated_at,
            uv_executable=args.uv_executable,
            python_executable=args.python_executable,
            installer_asset_dir=args.installer_asset_dir,
        )
    except (OSError, ReleaseBuildError) as exc:
        print(f"build-release: {exc}", file=sys.stderr)
        return 1
    if args.json_mode:
        print(json.dumps(result.to_json(), sort_keys=True))
    else:
        print(result.paths.release_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
