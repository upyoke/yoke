"""CI wheel sharing binds portable bytes to the exact tested checkout."""

import json
from pathlib import Path

import pytest

from runtime.api.cli.test_yoke_build_release import _write_wheel
from yoke_core.tools import ci_product_wheels as wheels


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    directory = tmp_path / "products"
    identity = {"commit": "a" * 40, "tree": "b" * 40}
    monkeypatch.setattr(wheels, "_identity", lambda _root: dict(identity))

    def build(**kwargs):
        kwargs["wheelhouse"].mkdir()
        for name in wheels.package_index.PRODUCT_PACKAGE_NAMES:
            _write_wheel(kwargs["wheelhouse"], name=name, version="0.2.0.202610140941")

    monkeypatch.setattr(wheels.build_release, "build_product_wheels", build)
    wheels.build_artifact(tmp_path, directory)
    return directory, identity


def test_products_are_copied_before_native_closure_and_remain_immutable(
    tmp_path, monkeypatch, artifact
):
    directory, _identity = artifact
    original = {p.name: p.read_bytes() for p in directory.iterdir()}
    closures = []

    def complete(**kwargs):
        target = kwargs["wheelhouse"]
        assert sorted(p.name for p in target.iterdir()) == sorted(
            name for name in original if name.endswith(".whl")
        )
        closures.append(target)
        (target / "native-dependency.whl").write_bytes(b"interpreter-specific")

    monkeypatch.setattr(wheels.build_release, "complete_product_wheelhouse", complete)
    for interpreter in ("old", "new"):
        wheels.consume_artifact(tmp_path, directory, tmp_path / interpreter)
    assert len(closures) == 2
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == original


@pytest.mark.parametrize("field", ["commit", "tree"])
def test_other_checkout_is_rejected_before_dependency_resolution(
    tmp_path, monkeypatch, artifact, field
):
    directory, identity = artifact
    identity[field] = "c" * 40
    monkeypatch.setattr(
        wheels.build_release, "complete_product_wheelhouse",
        lambda **_: pytest.fail("unverified products reached dependency resolution"),
    )
    with pytest.raises(ValueError, match="ci_product_wheels_invalid.*exact CI run"):
        wheels.consume_artifact(tmp_path, directory, tmp_path / "consumer")


@pytest.mark.parametrize("damage", ["hash", "missing", "native", "dependency"])
def test_incomplete_or_incompatible_artifact_refuses(tmp_path, artifact, damage):
    directory, _identity = artifact
    if damage == "hash":
        manifest = directory / wheels.MANIFEST
        data = json.loads(manifest.read_text())
        data["wheels"][next(iter(data["wheels"]))] = "0" * 64
        manifest.write_text(json.dumps(data))
    elif damage == "missing":
        (directory / wheels.MANIFEST).unlink()
    elif damage == "native":
        product = next(directory.glob("*.whl"))
        product.rename(Path(str(product).replace("py3-none-any", "cp314-cp314-manylinux_2_28_x86_64")))
    else:
        _write_wheel(directory, name="dependency", version="1.0")
    with pytest.raises(ValueError, match="ci_product_wheels_invalid"):
        wheels.consume_artifact(tmp_path, directory, tmp_path / "consumer")


def test_existing_mutable_wheelhouse_is_not_overwritten(tmp_path, artifact):
    directory, _identity = artifact
    target = tmp_path / "consumer"
    target.mkdir()
    owned = target / "existing"
    owned.write_text("preserve")
    with pytest.raises(ValueError, match="ci_product_wheelhouse_not_empty"):
        wheels.consume_artifact(tmp_path, directory, target)
    assert owned.read_text() == "preserve"


def test_dependency_failure_names_recovery(tmp_path, monkeypatch, artifact):
    directory, _identity = artifact

    def fail(**_kwargs):
        raise wheels.build_release.ReleaseBuildError("missing dependency")

    monkeypatch.setattr(wheels.build_release, "complete_product_wheelhouse", fail)
    with pytest.raises(ValueError, match="ci_product_wheel_closure_failed.*fresh per-job"):
        wheels.consume_artifact(tmp_path, directory, tmp_path / "consumer")
