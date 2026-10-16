"""CLI adapter for ``files.upload`` — upload a file, print its stable URL."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path
from typing import Any, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef

FILES_UPLOAD_USAGE = (
    "yoke files upload LOCAL_FILE [--path DEST/PATH.ext] [--project P] "
    "[--session-id S] [--json]"
)

FILES_UPLOAD_EPILOG = """\
Stores the file in the project's artifacts bucket (or, with none configured,
on the machine serving the universe) and prints a URL that stays valid:

  yoke files upload ./review.html --path plans/review.html
  -> https://<server>/v1/files/<project>/plans/review.html

Paste the URL into an item field, a strategy doc or anywhere else. Anyone
with items.read on the project opens it with a signed-in workbench browser
or an API token (Authorization: Bearer). Add ?download=1 to download.
Uploading to the same path replaces the file. Local mode links open while
`yoke ui` serves on its default port. Hosted files expire 365 days after
upload, like QA evidence. Guide: .yoke/docs/projects/shared-files.md
"""


def _local_ui_base() -> str:
    from yoke_contracts.local_ui_address import DEFAULT_UI_HOST, DEFAULT_UI_PORT

    return f"http://{DEFAULT_UI_HOST}:{DEFAULT_UI_PORT}"


def _with_url(response: Any, _actor: Any) -> Any:
    """Add the absolute URL for the connection that served the upload."""
    from yoke_cli.transport.https import resolve_https_connection
    from yoke_contracts.api_urls import join_api_url

    result = dict(response.result or {})
    if not response.success or not result.get("url_path"):
        return response
    connection = resolve_https_connection()
    base = connection.api_url if connection is not None else _local_ui_base()
    result["url"] = join_api_url(base, str(result["url_path"]))
    return response.model_copy(update={"result": result})


def _write_url(response: Any, stdout: TextIO, _stderr: TextIO) -> None:
    result = response.result or {}
    print(result["url"], file=stdout)


def files_upload(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke files upload",
        description=FILES_UPLOAD_USAGE,
        epilog=FILES_UPLOAD_EPILOG,
    )
    parser.add_argument("local_file", help="The local file to upload.")
    parser.add_argument(
        "--path",
        default=None,
        help=(
            "Destination path inside the project, '/'-separated segments of "
            "letters, digits, '.', '_' or '-' (default: the file name)."
        ),
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, FILES_UPLOAD_USAGE)
    if parsed is None:
        return 2
    source = Path(parsed.local_file).expanduser()
    try:
        content = source.read_bytes()
    except OSError as exc:
        return usage_error(f"cannot read {source}: {exc}")
    project = client_project_context(parsed.project)
    if project is None:
        return usage_error(
            "no project: pass --project, set YOKE_PROJECT, or run inside a "
            "checkout mapped to a project"
        )
    return dispatch_and_emit(
        function_id="files.upload",
        target=TargetRef(kind="global"),
        payload={
            "project": project,
            "path": parsed.path or source.name,
            "content_base64": base64.b64encode(content).decode("ascii"),
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_url,
        response_recovery=_with_url,
        timeout_s=120.0,
    )


__all__ = ["FILES_UPLOAD_USAGE", "files_upload"]
