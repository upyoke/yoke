"""Installed product bytes retain the attested wheel's original RECORD hashes."""

import base64
import csv
import hashlib
from importlib.metadata import PathDistribution
import io
import zipfile

import pytest

from yoke_core.tools import container_image_validation as subject


@pytest.fixture
def installed_wheels(tmp_path, monkeypatch):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    site = tmp_path / "site"
    site.mkdir()
    distributions = {}
    for suffix in ("cli", "contracts", "core", "harness"):
        name = f"yoke-{suffix}"
        module = f"yoke_{suffix}.py"
        info = f"yoke_{suffix}-1.0.dist-info"
        files = {
            module: b"VALUE = 42\n",
            f"{info}/METADATA": f"Name: {name}\nVersion: 1.0\n".encode(),
        }
        rows = []
        for filename, content in files.items():
            digest = (
                base64.urlsafe_b64encode(hashlib.sha256(content).digest())
                .decode()
                .rstrip("=")
            )
            rows.append([filename, f"sha256={digest}", str(len(content))])
        record = io.StringIO()
        csv.writer(record).writerows([*rows, [f"{info}/RECORD", "", ""]])
        files[f"{info}/RECORD"] = record.getvalue().encode()
        with zipfile.ZipFile(
            wheels / f"yoke_{suffix}-1.0-py3-none-any.whl", "w"
        ) as wheel:
            for filename, content in files.items():
                wheel.writestr(filename, content)
                installed = site / filename
                installed.parent.mkdir(exist_ok=True)
                installed.write_bytes(content)
        # Installers extend RECORD with generated entry points and bytecode.
        with (site / info / "RECORD").open("a") as stream:
            stream.write(f"{module}c,,\n")
        distributions[name] = PathDistribution(site / info)
    monkeypatch.setattr(subject, "distribution", distributions.__getitem__)
    return wheels, site


def test_every_original_record_hash_survives_install(installed_wheels, capsys):
    wheels, _ = installed_wheels
    subject.verify_installed_wheels(wheels)
    assert capsys.readouterr().out.count("Installed wheel RECORD verified:") == 4


@pytest.mark.parametrize(
    "corrupt", ["payload", "record", "missing-record", "missing-wheel"]
)
def test_installed_corruption_refuses(installed_wheels, corrupt):
    wheels, site = installed_wheels
    if corrupt == "payload":
        (site / "yoke_cli.py").write_bytes(b"changed")
    elif corrupt == "record":
        record = site / "yoke_cli-1.0.dist-info/RECORD"
        record.write_text(record.read_text().replace("sha256=", "sha512="))
    elif corrupt == "missing-record":
        (site / "yoke_cli-1.0.dist-info/RECORD").unlink()
    else:
        next(wheels.glob("*cli*.whl")).unlink()
    with pytest.raises(ValueError, match="installed_wheel_(record|set)_mismatch"):
        subject.verify_installed_wheels(wheels)
