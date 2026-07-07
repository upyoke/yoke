"""Browser QA — capture→presign→upload→record evidence flow."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain.browser_qa_steps import (
    _durable_artifact_handle,
    _upload_artifact,
)
from yoke_core.domain.browser_qa_test_helpers import (
    _FakeRunRecorder,
    _fetch_context_from_test_db,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


def _presign_payload(filename: str = "home.png") -> Dict[str, Any]:
    return {
        "upload_url": "https://b.s3.us-east-1.amazonaws.com/k?sig=x",
        "artifact_handle": {
            "backend": "s3",
            "bucket": "yoke-prod-artifacts",
            "key": f"qa-artifacts/testproj/100/1/{filename}",
            "content_type": "image/png",
        },
        "expires_in_s": 900,
        "environment": "prod",
    }


class TestDurableArtifactHandle:
    def test_presign_plus_upload_returns_s3_handle(self, tmp_path: Path) -> None:
        shot = tmp_path / "home.png"
        shot.write_bytes(b"PNG")
        with mock.patch.object(
            browser_qa, "_presign_artifact", return_value=_presign_payload(),
        ) as presign, mock.patch.object(
            browser_qa, "_upload_artifact", return_value=True,
        ) as upload:
            handle = _durable_artifact_handle(1, 10, str(shot), "image/png")
        assert handle["backend"] == "s3"
        assert handle["bucket"] == "yoke-prod-artifacts"
        presign.assert_called_once_with(1, 10, "home.png", "image/png")
        upload.assert_called_once_with(
            "https://b.s3.us-east-1.amazonaws.com/k?sig=x",
            str(shot), "image/png",
        )

    def test_presign_miss_degrades_to_explicit_local(self, tmp_path: Path) -> None:
        shot = tmp_path / "home.png"
        shot.write_bytes(b"PNG")
        with mock.patch.object(
            browser_qa, "_presign_artifact", return_value=None,
        ):
            handle = _durable_artifact_handle(1, 10, str(shot), "image/png")
        assert handle == {
            "backend": "local",
            "path": str(shot),
            "content_type": "image/png",
        }

    def test_upload_failure_degrades_to_explicit_local(self, tmp_path: Path) -> None:
        shot = tmp_path / "home.png"
        shot.write_bytes(b"PNG")
        with mock.patch.object(
            browser_qa, "_presign_artifact", return_value=_presign_payload(),
        ), mock.patch.object(
            browser_qa, "_upload_artifact", return_value=False,
        ):
            handle = _durable_artifact_handle(1, 10, str(shot), "image/png")
        assert handle["backend"] == "local"
        assert handle["path"] == str(shot)


class TestUploadArtifact:
    def test_puts_bytes_with_content_type(self, tmp_path: Path) -> None:
        shot = tmp_path / "home.png"
        shot.write_bytes(b"PNGBYTES")
        seen: Dict[str, Any] = {}

        class _Resp(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def _fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            seen["method"] = request.get_method()
            seen["content_type"] = request.get_header("Content-type")
            seen["body"] = request.data
            return _Resp()

        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            ok = _upload_artifact(
                "https://bkt.s3.amazonaws.com/k?sig=y", str(shot), "image/png",
            )
        assert ok is True
        assert seen["method"] == "PUT"
        assert seen["content_type"] == "image/png"
        assert seen["body"] == b"PNGBYTES"

    def test_network_error_returns_false(self, tmp_path: Path) -> None:
        shot = tmp_path / "home.png"
        shot.write_bytes(b"PNG")
        import urllib.error

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("down"),
        ):
            assert _upload_artifact("https://x/y", str(shot), "image/png") is False

    def test_missing_file_returns_false(self, tmp_path: Path) -> None:
        assert _upload_artifact(
            "https://x/y", str(tmp_path / "absent.png"), "image/png",
        ) is False


class TestScenarioRecordsUploadedHandles:
    def test_capture_upload_record_round_trip(
        self,
        tmp_path: Path,
        db_path: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """End-to-end: capture lands on disk, uploads, records the s3 handle."""
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path, 100, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "screenshot", "capture": True, "label": "home"},
                ],
            },
        )
        recorder = _FakeRunRecorder(db_path)
        uploads: List[Any] = []

        def _fake_step(_step, _base_url, artifact_dir, *args, **kwargs):
            shot = Path(artifact_dir) / "home.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(b"PNG")
            return {"success": True, "artifacts": [str(shot)]}

        def _fake_upload(url, path, content_type):
            uploads.append((url, path, content_type))
            return True

        def _fake_context(item_id, project, expected_branch=None):
            return _fetch_context_from_test_db(
                db_path, item_id, project, expected_branch,
            )

        patches = [
            mock.patch.object(
                browser_qa, "_fetch_browser_context", side_effect=_fake_context,
            ),
            mock.patch.object(
                browser_qa, "_validate_reachability", return_value=None,
            ),
            mock.patch.object(
                browser_qa, "_ensure_daemon_running", return_value=None,
            ),
            mock.patch.object(
                browser_qa, "_record_run", side_effect=recorder.record_run,
            ),
            mock.patch.object(
                browser_qa, "_complete_run", side_effect=recorder.complete_run,
            ),
            mock.patch.object(
                browser_qa, "_record_artifact",
                side_effect=recorder.record_artifact,
            ),
            mock.patch.object(
                browser_qa, "_presign_artifact",
                return_value=_presign_payload(),
            ),
            mock.patch.object(
                browser_qa, "_upload_artifact", side_effect=_fake_upload,
            ),
            mock.patch.object(browser_qa, "_execute_step", side_effect=_fake_step),
        ]
        for p in patches:
            p.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=100, project="testproj",
                base_url="http://localhost:9999",
            )
        finally:
            for p in reversed(patches):
                p.stop()

        assert result.verdict == "pass"
        assert len(uploads) == 1
        assert uploads[0][2] == "image/png"

        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT artifact_handle FROM qa_artifacts ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        handle = json.loads(row[0])
        assert handle["backend"] == "s3"
        assert handle["bucket"] == "yoke-prod-artifacts"
        # The in-session inspection path still points at the local capture.
        assert result.runs[0].artifacts
        assert Path(result.runs[0].artifacts[0]).is_file()
