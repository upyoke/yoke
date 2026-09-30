"""A reviewer can read one region of a tall capture, or refuse knowing why.

A full-page screenshot of a long screen is unreadable once a viewer scales it
to fit, so the read surface renders the recorded bytes into the part being
judged. These cover the rendering contract and every refusal, because a view
that silently returned the whole image would be evidence the reader believes
is the region they asked for.
"""

from __future__ import annotations

import base64
import builtins
import io
import struct
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.qa_artifact_image_view import (
    MAX_SCALE,
    ArtifactViewError,
    apply_artifact_view,
    parse_region,
    parse_scale,
    refuse_unsupported_content_type,
)

ADAPTER = "yoke_cli.commands.adapters.qa_execution_subjects"


def _png(width: int, height: int) -> bytes:
    """Build a solid PNG without depending on an optional image library."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row += bytes(((x * 7) % 256, (y * 11) % 256, 90))
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _response(result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="qa.artifact.read",
        request_id="artifact-read",
        version="v1",
        result=result,
    )


def _read(destination: Path, *flags: str) -> tuple[int, str, str]:
    """Run the read CLI against inline bytes, returning code and streams."""
    out, err = io.StringIO(), io.StringIO()
    with (
        patch(
            f"{ADAPTER}.call_dispatcher",
            return_value=_response(
                {
                    "disposition": "inline",
                    "content_type": "image/png",
                    "content_base64": base64.b64encode(_png(400, 1200)).decode(),
                }
            ),
        ),
        patch(f"{ADAPTER}.ensure_handlers_loaded"),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        code = cli_main(
            [
                "qa",
                "artifact",
                "read",
                "--requirement-id",
                "1",
                "--artifact-id",
                "2",
                "--output",
                str(destination),
                *flags,
            ]
        )
    return code, out.getvalue(), err.getvalue()


def test_region_renders_only_the_named_rectangle(tmp_path) -> None:
    destination = tmp_path / "evidence.png"
    code, _out, err = _read(destination, "--region", "0,900,400,300")

    assert code == 0, err
    assert _png_size(destination) == (400, 300)


def test_scale_renders_the_whole_capture_smaller(tmp_path) -> None:
    destination = tmp_path / "evidence.png"
    code, _out, err = _read(destination, "--scale", "0.5")

    assert code == 0, err
    assert _png_size(destination) == (200, 600)


def test_region_and_scale_compose_region_first(tmp_path) -> None:
    destination = tmp_path / "evidence.png"
    code, _out, err = _read(destination, "--region", "0,0,400,300", "--scale", "2")

    assert code == 0, err
    assert _png_size(destination) == (800, 600)


def test_a_plain_read_still_lands_the_recorded_bytes(tmp_path) -> None:
    destination = tmp_path / "evidence.png"
    code, _out, err = _read(destination)

    assert code == 0, err
    assert _png_size(destination) == (400, 1200)


def test_a_region_outside_the_image_refuses_and_keeps_the_bytes(tmp_path) -> None:
    destination = tmp_path / "evidence.png"
    code, _out, err = _read(destination, "--region", "0,0,4000,4000")

    assert code == 1
    assert "falls outside the 400x1200 image" in err
    # The recorded bytes are already on disk, so the reader is told where they
    # are rather than losing the read along with the view.
    assert str(destination.resolve()) in err
    assert _png_size(destination) == (400, 1200)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1,2,3", "four comma-separated integers"),
        ("0,0,0,10", "must be positive"),
        ("0,0,-4,10", "must be positive"),
        ("-1,0,4,10", "cannot be negative"),
        ("a,0,4,10", "must be an integer number of pixels"),
    ],
)
def test_a_malformed_region_names_what_it_needed(value, expected) -> None:
    with pytest.raises(ArtifactViewError) as refusal:
        parse_region(value)
    assert expected in str(refusal.value)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0", "greater than zero"),
        ("-2", "greater than zero"),
        ("nope", "must be a number"),
        (str(MAX_SCALE + 1), f"exceeds the {MAX_SCALE} maximum"),
    ],
)
def test_a_malformed_scale_names_what_it_needed(value, expected) -> None:
    with pytest.raises(ArtifactViewError) as refusal:
        parse_scale(value)
    assert expected in str(refusal.value)


def test_a_non_image_artifact_refuses_the_view() -> None:
    with pytest.raises(ArtifactViewError) as refusal:
        refuse_unsupported_content_type("application/json")
    message = str(refusal.value)
    assert "application/json" in message
    assert "without those flags" in message


def test_an_unstated_content_type_refuses_rather_than_guessing() -> None:
    with pytest.raises(ArtifactViewError) as refusal:
        refuse_unsupported_content_type(None)
    assert "unknown" in str(refusal.value)


def test_a_supported_content_type_is_accepted() -> None:
    # Charset parameters travel on recorded content types, so the check reads
    # the media type rather than the whole header.
    refuse_unsupported_content_type("image/png")
    refuse_unsupported_content_type("image/jpeg; charset=binary")


def test_a_view_with_neither_region_nor_scale_refuses(tmp_path) -> None:
    source = tmp_path / "capture.png"
    source.write_bytes(_png(40, 60))
    with pytest.raises(ArtifactViewError) as refusal:
        apply_artifact_view(source)
    assert "region, a scale, or both" in str(refusal.value)


def test_the_view_reports_which_pixels_the_reader_received(tmp_path) -> None:
    source = tmp_path / "capture.png"
    source.write_bytes(_png(400, 1200))

    applied = apply_artifact_view(
        source,
        region=parse_region("10,20,100,50"),
        scale=parse_scale("2"),
    )

    assert applied["source_size"] == [400, 1200]
    assert applied["region"] == [10, 20, 100, 50]
    assert applied["scale"] == 2.0
    assert applied["size"] == [200, 100]
    assert applied["backend"] in {"pillow", "sips"}
    assert _png_size(source) == (200, 100)


def test_a_missing_renderer_refuses_and_names_the_repair(tmp_path) -> None:
    source = tmp_path / "capture.png"
    source.write_bytes(_png(40, 60))

    # Pillow is a required dependency, so its absence is a broken install
    # rather than a choice -- the refusal has to name the repair, not a flag.
    real_import = builtins.__import__

    def without_pillow(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("No module named 'PIL'")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", without_pillow):
        with pytest.raises(ArtifactViewError) as refusal:
            apply_artifact_view(source, scale=parse_scale("0.5"))

    message = str(refusal.value)
    assert "need Pillow" in message
    assert "pip install --upgrade yoke-cli" in message
    # The read still delivered the recorded bytes, so say so.
    assert "without those flags" in message
    assert _png_size(source) == (40, 60)


def test_the_json_read_carries_the_view_it_rendered(tmp_path) -> None:
    import json

    destination = tmp_path / "evidence.png"
    code, out, err = _read(destination, "--region", "0,0,400,300", "--json")

    assert code == 0, err
    payload = json.loads(out)
    view = payload["result"]["artifact_view"]
    assert view["region"] == [0, 0, 400, 300]
    assert view["size"] == [400, 300]
