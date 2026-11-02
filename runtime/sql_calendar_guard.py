"""Scan executed SQL calendar buckets; leave Python clock code to behavior tests."""

import re

import psycopg
import pytest


def unsafe_buckets(sql):
    """Inspect each SQL calendar operation, excluding other operations' zones."""
    bad = []
    for match in re.finditer(r"\b(?:to_char|date_trunc)\s*\(", sql, re.I):
        start = match.end()
        depth = 1
        end = start
        while end < len(sql) and depth:
            if sql[end] == "(":
                depth += 1
            elif sql[end] == ")":
                depth -= 1
            end += 1
        expression = sql[start : end - 1]
        # Numeric templates carry digit positions; calendar templates carry
        # date/time fields, including short formats such as DD and HH24.
        templates = re.findall(r"'([^']*)'", expression)
        template = templates[-1] if templates else ""
        calendar = bool(re.search(r"[A-Za-z]", template)) and not re.search(
            r"[90]|\bRN\b", template, re.I
        )
        if match.group().lower().startswith("date_trunc") or calendar:
            if not re.search(r"AT\s+TIME\s+ZONE\s+'UTC'", expression, re.I):
                bad.append(match.group() + expression)
    for match in re.finditer(r"::\s*date\b", sql, re.I):
        prefix = sql[: match.start()].rstrip()
        if prefix.endswith(")"):
            depth = 1
            start = len(prefix) - 2
            while start >= 0 and depth:
                if prefix[start] == ")":
                    depth += 1
                elif prefix[start] == "(":
                    depth -= 1
                start -= 1
            operand = prefix[start + 1 :]
        else:
            operand = re.search(r"[\w.]+$", prefix).group()
        if not re.search(r"AT\s+TIME\s+ZONE\s+'UTC'", operand, re.I):
            bad.append(operand + "::date")
    return bad


@pytest.fixture(autouse=True)
def _guard_sql_calendar_buckets(monkeypatch):
    execute = psycopg.Cursor.execute

    def checked(cursor, query, *args, **kwargs):
        if isinstance(query, str):
            violations = unsafe_buckets(query)
            assert not violations, (
                "sql_instant_bucket_session_zone: apply AT TIME ZONE 'UTC' "
                f"to each instant before a calendar bucket: {violations}"
            )
        return execute(cursor, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Cursor, "execute", checked)
