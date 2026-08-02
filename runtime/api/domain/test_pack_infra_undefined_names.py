"""Pack infrastructure programs must not reference undefined names.

These modules are never imported by the test suite — they run only inside a
Pulumi program, against a Pulumi runtime the tests do not have. A name that
was never imported therefore survives every test and surfaces as a NameError
partway through a real `pulumi up`, after the change has merged and while a
live stack is mid-update.

Moving a function between modules is the usual way to introduce one: the
body travels, the import it depended on does not.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from yoke_core.domain.pack_catalog import load_pack_descriptor, packs_root

#: Packs whose ``files/infra`` tree is executed as a Pulumi program.
_INFRA_PACKS = ("pulumi-foundation", "self-hosted-runners", "vps-hosting")


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is unavailable")
@pytest.mark.parametrize("slug", _INFRA_PACKS)
def test_latest_pack_infra_has_no_undefined_names(slug):
    descriptor = load_pack_descriptor(slug)
    infra = (
        packs_root() / slug / "versions"
        / descriptor["latest_version"] / "files" / "infra"
    )
    if not infra.is_dir():
        pytest.skip(f"{slug} ships no infra tree")

    # F821 is pyflakes' undefined-name rule; it is the one check that catches
    # a moved function whose import stayed behind.
    result = subprocess.run(
        ["ruff", "check", "--select", "F821", "--no-cache", str(infra)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{slug} infra references undefined names:\n{result.stdout}"
    )
