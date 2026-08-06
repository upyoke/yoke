"""Catalog grammar and data-target allowlist for portable archives."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from yoke_core.domain.universe_portability_common import ArchiveInvalidError
from yoke_core.domain.universe_portability_content_contract import (
    ARCHIVE_FORBIDDEN_SEQUENCE_DATA,
    ARCHIVE_FORBIDDEN_TABLE_DATA,
)


RESTORED_DATA_TOC_KINDS = ("SEQUENCE SET", "TABLE DATA")
OMITTED_TOC_KINDS = (
    "SEQUENCE OWNED BY",
    "TABLE ATTACH",
    "FK CONSTRAINT",
    "CHECK CONSTRAINT",
    "INDEX ATTACH",
    "TEXT SEARCH CONFIGURATION",
    "TEXT SEARCH DICTIONARY",
    "TEXT SEARCH PARSER",
    "TEXT SEARCH TEMPLATE",
    "FOREIGN DATA WRAPPER",
    "MATERIALIZED VIEW DATA",
    "PROCEDURAL LANGUAGE",
    "PUBLICATION TABLE",
    "DEFAULT ACL",
    "DOMAIN CONSTRAINT",
    "EVENT TRIGGER",
    "FOREIGN SERVER",
    "FOREIGN TABLE",
    "MATERIALIZED VIEW",
    "OPERATOR CLASS",
    "OPERATOR FAMILY",
    "SECURITY LABEL",
    "USER MAPPING",
    "AGGREGATE",
    "BLOB COMMENTS",
    "COLLATION",
    "CONVERSION",
    "DATABASE",
    "EXTENSION",
    "FUNCTION",
    "OPERATOR",
    "POLICY",
    "PROCEDURE",
    "PUBLICATION",
    "ROW SECURITY",
    "STATISTICS",
    "SUBSCRIPTION",
    "TRANSFORM",
    "TRIGGER",
    "TYPE",
    "BLOB",
    "CAST",
    "COMMENT",
    "CONSTRAINT",
    "SEQUENCE",
    "DEFAULT",
    "INDEX",
    "TABLE",
    "DOMAIN",
    "PROCACT_SCHEMA",
    "RULE",
    "SCHEMA",
    "VIEW",
    "ACL",
)
TOC_KINDS = tuple(
    sorted(
        set(RESTORED_DATA_TOC_KINDS + OMITTED_TOC_KINDS),
        key=lambda value: (-len(value), value),
    )
)
TOC_ROW_RE = re.compile(r"^\d+;\s+\d+\s+\d+\s+(.+)$")
SAFE_RESTORE_OBJECT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def toc_kind_and_namespace(line: str) -> tuple[str, str]:
    match = TOC_ROW_RE.fullmatch(line)
    if match is None:
        raise ArchiveInvalidError(
            "the universe archive contains an unrecognized catalog row"
        )
    remainder = match.group(1)
    for kind in TOC_KINDS:
        prefix = kind + " "
        if not remainder.startswith(prefix):
            continue
        tail = remainder[len(prefix) :]
        namespace = tail.split(" ", 1)[0]
        if kind == "SCHEMA":
            parts = tail.split(" ", 2)
            if len(parts) < 2 or parts[0] != "-" or parts[1] != "public":
                raise ArchiveInvalidError(
                    "the universe archive contains SCHEMA outside public schema"
                )
            return kind, "public"
        if namespace != "public":
            raise ArchiveInvalidError(
                f"the universe archive contains {kind} outside public schema"
            )
        return kind, namespace
    raise ArchiveInvalidError(
        "the universe archive contains an unsupported catalog object kind"
    )


def validate_catalog(catalog: str) -> int:
    """Validate catalog object kinds and return the relation-entry count."""
    table_entries = 0
    has_org_table = False
    for line in catalog.splitlines():
        if not line or line.startswith(";"):
            continue
        kind, _namespace = toc_kind_and_namespace(line)
        if kind == "TABLE DATA" and any(
            f" TABLE DATA public {table} " in line
            for table in ARCHIVE_FORBIDDEN_TABLE_DATA
        ):
            raise ArchiveInvalidError(
                "the universe archive contains environment-owned secret data"
            )
        if kind == "SEQUENCE SET" and any(
            f" SEQUENCE SET public {sequence} " in line
            for sequence in ARCHIVE_FORBIDDEN_SEQUENCE_DATA
        ):
            raise ArchiveInvalidError(
                "the universe archive contains environment-owned secret sequence data"
            )
        if kind in ("TABLE", "TABLE DATA"):
            table_entries += 1
        if kind == "TABLE" and " TABLE public organizations " in line:
            has_org_table = True
    if table_entries == 0 or not has_org_table:
        raise ArchiveInvalidError("the archive contains no Yoke organization table")
    return table_entries


def catalog_data_targets(catalog: str) -> tuple[set[str], set[str]]:
    """Return canonical public table/sequence names enabled for data restore."""
    tables: set[str] = set()
    sequences: set[str] = set()
    for line in catalog.splitlines():
        if not line or line.startswith(";"):
            continue
        match = TOC_ROW_RE.fullmatch(line)
        if match is None:
            raise ArchiveInvalidError(
                "the universe archive contains an unrecognized catalog row"
            )
        remainder = match.group(1)
        for kind, sink in (("TABLE DATA", tables), ("SEQUENCE SET", sequences)):
            prefix = f"{kind} public "
            if not remainder.startswith(prefix):
                continue
            object_name = remainder[len(prefix) :].split(" ", 1)[0]
            if SAFE_RESTORE_OBJECT_RE.fullmatch(object_name) is None:
                raise ArchiveInvalidError(
                    f"the universe archive contains a noncanonical {kind} name"
                )
            sink.add(object_name)
            break
    return tables, sequences


def write_restore_list(catalog: str) -> Path:
    """Write a private pg_restore list enabling only public data entries."""
    descriptor, raw_path = tempfile.mkstemp(prefix="yoke-universe-", suffix=".toc")
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for line in catalog.splitlines():
                if not line or line.startswith(";"):
                    stream.write(line + "\n")
                    continue
                kind, _namespace = toc_kind_and_namespace(line)
                if kind in RESTORED_DATA_TOC_KINDS:
                    stream.write(line + "\n")
                else:
                    stream.write(";" + line + "\n")
        path.chmod(0o600)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


__all__ = [
    "OMITTED_TOC_KINDS",
    "RESTORED_DATA_TOC_KINDS",
    "SAFE_RESTORE_OBJECT_RE",
    "TOC_KINDS",
    "TOC_ROW_RE",
    "catalog_data_targets",
    "toc_kind_and_namespace",
    "validate_catalog",
    "write_restore_list",
]
