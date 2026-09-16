"""The artifact CLI materializes every portable read disposition."""

from __future__ import annotations

import base64
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_cli.qa_artifact_download import ArtifactDownloadError, download_artifact
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.free_paths import is_under_free_path_prefix


def _response(result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="qa.artifact.read",
        request_id="artifact-read",
        version="v1",
        result=result,
    )


class _DownloadResponse(io.BytesIO):
    def __init__(self, body: bytes, url: str) -> None:
        super().__init__(body)
        self.headers = {"content-length": str(len(body))}
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def geturl(self) -> str:
        return self._url


def test_authorized_download_is_bounded_and_atomic(tmp_path) -> None:
    url = "https://artifacts.example/evidence.png?signature=x"
    target = tmp_path / "nested" / "evidence.png"
    with patch(
        "yoke_cli.qa_artifact_download.open_bounded_request",
        return_value=_DownloadResponse(b"PNG", url),
    ) as opened:
        assert download_artifact(url, target) == 3

    assert target.read_bytes() == b"PNG"
    assert target.stat().st_mode & 0o777 == 0o600
    assert opened.call_args.kwargs["allow_loopback_http"] is False


def test_authorized_download_rejects_a_redirected_final_url(tmp_path) -> None:
    url = "https://artifacts.example/evidence.png?signature=x"
    with patch(
        "yoke_cli.qa_artifact_download.open_bounded_request",
        return_value=_DownloadResponse(b"PNG", "https://elsewhere.example/file"),
    ):
        try:
            download_artifact(url, tmp_path / "evidence.png")
        except ArtifactDownloadError as exc:
            assert "final URL did not match" in str(exc)
        else:
            raise AssertionError("redirected artifact URL was accepted")


def test_output_downloads_a_ready_authorized_url(tmp_path) -> None:
    destination = tmp_path / "evidence.png"
    with (
        patch(
            "yoke_cli.commands.adapters.qa_execution_subjects.call_dispatcher",
            return_value=_response(
                {
                    "disposition": "ready",
                    "download_url": "https://artifacts.example/evidence.png?signature=x",
                }
            ),
        ),
        patch(
            "yoke_cli.commands.adapters.qa_execution_subjects.download_artifact",
            return_value=3,
        ) as download,
        patch(
            "yoke_cli.commands.adapters.qa_execution_subjects.ensure_handlers_loaded"
        ),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        code = cli_main(
            [
                "qa",
                "artifact",
                "read",
                "--requirement-id",
                "31",
                "--artifact-id",
                "4",
                "--output",
                str(destination),
            ]
        )

    assert code == 0
    download.assert_called_once_with(
        "https://artifacts.example/evidence.png?signature=x",
        destination,
    )


def test_output_fails_when_authorized_bytes_cannot_be_downloaded(tmp_path) -> None:
    error = io.StringIO()
    with (
        patch(
            "yoke_cli.commands.adapters.qa_execution_subjects.call_dispatcher",
            return_value=_response(
                {
                    "disposition": "ready",
                    "download_url": "https://artifacts.example/evidence.png",
                }
            ),
        ),
        patch(
            "yoke_cli.commands.adapters.qa_execution_subjects.download_artifact",
            side_effect=ArtifactDownloadError("download timed out"),
        ),
        patch(
            "yoke_cli.commands.adapters.qa_execution_subjects.ensure_handlers_loaded"
        ),
        redirect_stdout(io.StringIO()),
        redirect_stderr(error),
    ):
        code = cli_main(
            [
                "qa",
                "artifact",
                "read",
                "--requirement-id",
                "31",
                "--artifact-id",
                "4",
                "--output",
                str(tmp_path / "evidence.png"),
            ]
        )

    assert code == 1
    assert "download timed out" in error.getvalue()


def _read_without_output(result: dict, out: io.StringIO, err: io.StringIO) -> int:
    with (
        patch(
            "yoke_cli.commands.adapters.qa_execution_subjects.call_dispatcher",
            return_value=_response(result),
        ),
        patch(
            "yoke_cli.commands.adapters.qa_execution_subjects.ensure_handlers_loaded"
        ),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        return cli_main(
            [
                "qa",
                "artifact",
                "read",
                "--requirement-id",
                "31",
                "--artifact-id",
                "4",
                "--json",
            ]
        )


def test_read_without_output_lands_bytes_at_a_guard_admitted_path() -> None:
    out = io.StringIO()
    code = _read_without_output(
        {
            "disposition": "ready",
            "content_type": "image/png",
            "content_base64": base64.b64encode(b"PNG").decode("ascii"),
        },
        out,
        io.StringIO(),
    )

    assert code == 0
    landed = Path(json.loads(out.getvalue())["result"]["path"])
    assert landed.read_bytes() == b"PNG"
    assert landed.suffix == ".png"
    # The whole point of the default: a reviewer may open what it names.
    assert is_under_free_path_prefix(landed)
    landed.unlink()


def test_read_without_output_drops_the_inline_copy_of_landed_bytes() -> None:
    out = io.StringIO()
    code = _read_without_output(
        {
            "disposition": "ready",
            "content_type": "image/png",
            "content_base64": base64.b64encode(b"PNG").decode("ascii"),
        },
        out,
        io.StringIO(),
    )

    assert code == 0
    result = json.loads(out.getvalue())["result"]
    assert "content_base64" not in result
    Path(result["path"]).unlink()


def test_read_names_the_disposition_when_no_bytes_can_be_landed() -> None:
    err = io.StringIO()
    code = _read_without_output(
        {
            "disposition": "evidence_on_machine",
            "machine": "test-mac-01",
            "detail": "the evidence bytes are not present on this machine",
        },
        io.StringIO(),
        err,
    )

    assert code == 1
    message = err.getvalue()
    assert "evidence_on_machine" in message
    assert "test-mac-01" in message
    assert "not present on this machine" in message
