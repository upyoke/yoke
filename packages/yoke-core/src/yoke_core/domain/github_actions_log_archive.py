"""Resource-safe parsing for GitHub Actions log archives."""

from __future__ import annotations

import io
import zipfile
from typing import Dict

from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.github_response_safety import (
    GITHUB_SMALL_RESPONSE_LIMIT_BYTES as GITHUB_ACTIONS_LOG_READ_CHUNK_BYTES,
)


GITHUB_ACTIONS_LOG_ARCHIVE_LIMIT_BYTES = 64 * 1024 * 1024
GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES = 32 * 1024 * 1024
GITHUB_ACTIONS_LOG_TOTAL_LIMIT_BYTES = 128 * 1024 * 1024
GITHUB_ACTIONS_LOG_ENTRY_COUNT_LIMIT = 2_048
GITHUB_ACTIONS_LOG_COMPRESSION_RATIO_LIMIT = 200


class ActionsLogArchiveError(RestTransportError):
    """A GitHub Actions log archive violated its safe parsing envelope."""

    code = "actions_log_archive_error"


def parse_failed_log_zip(zip_bytes: bytes) -> Dict[str, str]:
    """Extract bounded top-level per-job text from one workflow log ZIP."""
    if not zip_bytes:
        return {}
    if len(zip_bytes) > GITHUB_ACTIONS_LOG_ARCHIVE_LIMIT_BYTES:
        raise ActionsLogArchiveError(
            "GitHub Actions log archive exceeded the compressed size limit"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            infos = archive.infolist()
            if len(infos) > GITHUB_ACTIONS_LOG_ENTRY_COUNT_LIMIT:
                raise ActionsLogArchiveError(
                    "GitHub Actions log archive contained too many entries"
                )
            relevant = [info for info in infos if _is_job_log(info)]
            _validate_relevant_entries(relevant)
            return _read_relevant_entries(archive, relevant)
    except ActionsLogArchiveError:
        raise
    except Exception:
        raise ActionsLogArchiveError(
            "GitHub Actions log archive was invalid or corrupted"
        ) from None


def _is_job_log(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    return not info.is_dir() and "/" not in name and name.endswith(".txt")


def _validate_relevant_entries(infos: list[zipfile.ZipInfo]) -> None:
    total = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise ActionsLogArchiveError(
                "GitHub Actions log archive contained an encrypted entry"
            )
        if info.file_size < 0 or info.compress_size < 0:
            raise ActionsLogArchiveError(
                "GitHub Actions log archive contained invalid entry sizes"
            )
        if info.file_size > GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES:
            raise ActionsLogArchiveError(
                "GitHub Actions log archive entry exceeded the size limit"
            )
        if _exceeds_compression_ratio(info):
            raise ActionsLogArchiveError(
                "GitHub Actions log archive entry exceeded the compression ratio limit"
            )
        total += info.file_size
        if total > GITHUB_ACTIONS_LOG_TOTAL_LIMIT_BYTES:
            raise ActionsLogArchiveError(
                "GitHub Actions log archive exceeded the expanded size limit"
            )


def _exceeds_compression_ratio(info: zipfile.ZipInfo) -> bool:
    if info.file_size == 0:
        return False
    if info.compress_size == 0:
        return True
    return (
        info.file_size > info.compress_size * GITHUB_ACTIONS_LOG_COMPRESSION_RATIO_LIMIT
    )


def _read_relevant_entries(
    archive: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
) -> Dict[str, str]:
    result: Dict[str, str] = {}
    expanded_so_far = 0
    for info in infos:
        body_bytes = _read_entry_bounded(
            archive,
            info,
            expanded_so_far=expanded_so_far,
        )
        if len(body_bytes) != info.file_size:
            raise ActionsLogArchiveError(
                "GitHub Actions log archive entry size did not match metadata"
            )
        expanded_so_far += len(body_bytes)
        job_name = _job_name_from_entry(info.filename)
        if job_name:
            result[job_name] = body_bytes.decode("utf-8", errors="replace")
    return result


def _read_entry_bounded(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    expanded_so_far: int,
) -> bytes:
    ratio_limit = info.compress_size * GITHUB_ACTIONS_LOG_COMPRESSION_RATIO_LIMIT
    remaining_total = GITHUB_ACTIONS_LOG_TOTAL_LIMIT_BYTES - expanded_so_far
    safe_limit = min(
        GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES,
        remaining_total,
        ratio_limit,
    )
    body = bytearray()
    with archive.open(info, "r") as source:
        while True:
            read_size = min(
                GITHUB_ACTIONS_LOG_READ_CHUNK_BYTES,
                safe_limit - len(body) + 1,
            )
            chunk = source.read(max(1, read_size))
            if not chunk:
                break
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise ActionsLogArchiveError(
                    "GitHub Actions log archive entry did not return bytes"
                )
            if len(chunk) > max(1, read_size):
                raise ActionsLogArchiveError(
                    "GitHub Actions log archive entry violated the bounded read"
                )
            body.extend(chunk)
            _check_actual_expanded_size(
                len(body),
                expanded_so_far=expanded_so_far,
                ratio_limit=ratio_limit,
            )
    return bytes(body)


def _check_actual_expanded_size(
    entry_size: int,
    *,
    expanded_so_far: int,
    ratio_limit: int,
) -> None:
    if entry_size > GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES:
        raise ActionsLogArchiveError(
            "GitHub Actions log archive entry exceeded the size limit"
        )
    if expanded_so_far + entry_size > GITHUB_ACTIONS_LOG_TOTAL_LIMIT_BYTES:
        raise ActionsLogArchiveError(
            "GitHub Actions log archive exceeded the expanded size limit"
        )
    if entry_size > ratio_limit:
        raise ActionsLogArchiveError(
            "GitHub Actions log archive entry exceeded the compression ratio limit"
        )


def _job_name_from_entry(filename: str) -> str:
    stem = filename.removesuffix(".txt")
    head, separator, tail = stem.partition("_")
    return tail if separator and head.isdigit() else stem


__all__ = [
    "ActionsLogArchiveError",
    "GITHUB_ACTIONS_LOG_ARCHIVE_LIMIT_BYTES",
    "GITHUB_ACTIONS_LOG_COMPRESSION_RATIO_LIMIT",
    "GITHUB_ACTIONS_LOG_ENTRY_COUNT_LIMIT",
    "GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES",
    "GITHUB_ACTIONS_LOG_READ_CHUNK_BYTES",
    "GITHUB_ACTIONS_LOG_TOTAL_LIMIT_BYTES",
    "parse_failed_log_zip",
]
