"""Preview cleanup renders canonical log clocks and retains frozen Pack sources."""

from datetime import timezone
import hashlib
from pathlib import Path
import runpy

import pytest

from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.pack_render import render_pack_text

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs/branch-preview-hosting"
FROZEN = {
    "docs/packs/branch-preview-hosting/README.md": "01348d0241de8edea2ab270dc6aef6e85e42f1d3e52b3d5a00053e0b66bb3c15",
    "ops/ephemeral_cleanup.py": "6b4624745344d41412848fcdb7ef55cdb3afd40bfa2cf63c0772945e94f8fe47",
    "ops/ephemeral_port.js": "05128ec683c8c5a6d6b0bacfbdbe4caa8e8ab44d528ba9cd9bc6e585df4029d9",
    "ops/nginx-ephemeral.conf": "a3849e23590fc816dd9ae411ade2cc9d967a442efad8b34537a7d88c489c49c3",
}


@pytest.mark.parametrize(
    "source",
    [
        ROOT / "ops/ephemeral_cleanup.py",
        PACK / "versions/1.1.1/files/ops/ephemeral_cleanup.py",
    ],
)
@pytest.mark.parametrize(
    "clock",
    [
        "1969-12-31T23:59:59.123456Z",
        "0042-01-02T03:04:05.000006Z",
        "2024-02-29T00:00:00.456789Z",
        "2026-01-01T00:00:00.000000Z",
    ],
)
def test_cleanup_log_owns_fixed_six_utc_clock(
    tmp_path, monkeypatch, capsys, source, clock
):
    rendered = tmp_path / "cleanup.py"
    rendered.write_text(
        render_pack_text(
            source.read_text(),
            {"preview_namespace": "sample-preview", "preview_ttl_hours": "24"},
        )
    )
    program = runpy.run_path(str(rendered), run_name="cleanup_clock_test")
    instant = parse_instant(clock)

    class Clock:
        @staticmethod
        def now(zone):
            assert zone is timezone.utc
            return instant

    monkeypatch.setitem(program["log"].__globals__, "datetime", Clock)
    message = "clock-looking vendor text 2026-01-01T00:00:00Z"
    program["log"](message)
    assert (
        capsys.readouterr().out
        == f"{format_instant(instant)} [preview-cleanup] {message}\n"
    )


def test_frozen_cleanup_pack_files_keep_exact_bytes():
    frozen = PACK / "versions/1.1.0/files"
    actual = {
        str(p.relative_to(frozen)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in frozen.rglob("*")
        if p.is_file()
    }
    assert actual == FROZEN
