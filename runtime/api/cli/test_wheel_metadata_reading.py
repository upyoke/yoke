"""Wheel identity comes from root metadata, never a vendored distribution."""

import zipfile

import pytest

from yoke_core.tools import package_index


def test_wheel_identity_ignores_vendored_metadata(tmp_path):
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        # Put vendored metadata first so archive order cannot select identity.
        archive.writestr(
            "example/_vendor/other-2.0.dist-info/METADATA",
            "Name: other\nVersion: 2.0\n",
        )
        archive.writestr(
            "example-1.0.dist-info/METADATA", "Name: example\nVersion: 1.0\n"
        )

    record = package_index.read_wheel_record(wheel)
    assert record.name == "example"
    assert record.version == "1.0"


@pytest.mark.parametrize("root_metadata", [(), ("first", "second")])
def test_wheel_requires_exactly_one_root_metadata_file(tmp_path, root_metadata):
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "example/_vendor/other-2.0.dist-info/METADATA",
            "Name: other\nVersion: 2.0\n",
        )
        for name in root_metadata:
            archive.writestr(
                f"{name}-1.0.dist-info/METADATA", f"Name: {name}\nVersion: 1.0\n"
            )

    with pytest.raises(ValueError, match="no single METADATA file"):
        package_index.read_wheel_record(wheel)
