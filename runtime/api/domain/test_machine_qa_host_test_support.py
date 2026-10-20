"""The machine-QA fixture connection behaves like a connection in ``with``."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.machine_qa_host_test_support import OpenFixtureConnection


def test_fixture_connection_commits_on_exit_and_stays_open() -> None:
    inner = mock.Mock()

    with OpenFixtureConnection(inner) as conn:
        conn.execute("SELECT 1")

    inner.execute.assert_called_once_with("SELECT 1")
    inner.commit.assert_called_once_with()
    inner.rollback.assert_not_called()
    inner.close.assert_not_called()


def test_fixture_connection_rolls_back_and_reraises_on_error() -> None:
    inner = mock.Mock()

    with pytest.raises(RuntimeError, match="boom"):
        with OpenFixtureConnection(inner):
            raise RuntimeError("boom")

    inner.rollback.assert_called_once_with()
    inner.commit.assert_not_called()
    inner.close.assert_not_called()
