"""Public item selectors and filter argument validation for the events CLI."""

from __future__ import annotations

from yoke_core.domain import events_crud as ec
from runtime.api.events_crud_test_fixtures import _insert_event, db_path as db_path


class TestListErgonomics:
    """Events list ergonomics."""

    def test_list_help_prints_usage_and_exits_zero(self, db_path, monkeypatch, capsys):
        """--help shows usage instead of dumping ledger rows."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="help-1")
        assert ec.main(["list", "--help"]) == 0
        out = capsys.readouterr().out
        assert "Usage: events list" in out
        assert "help-1" not in out  # ledger NOT queried

    def test_list_short_help_flag_also_works(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="help-2")
        assert ec.main(["list", "-h"]) == 0
        out = capsys.readouterr().out
        assert "Usage: events list" in out
        assert "help-2" not in out

    def test_list_unknown_flag_fails_closed(self, db_path, monkeypatch, capsys):
        """Unknown filter flags exit 2 instead of silently filtering nothing."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="bogus-1")
        assert ec.main(["list", "--bogus", "x"]) == 2
        err = capsys.readouterr().err
        assert "unknown filter flag" in err and "--bogus" in err

    def test_list_missing_value_fails_closed(self, db_path, monkeypatch, capsys):
        """A flag with no value is rejected with a clear error."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="missingval-1")
        assert ec.main(["list", "--item"]) == 2
        assert "requires a value" in capsys.readouterr().err

    def test_list_filter_value_cannot_be_next_flag(self, db_path, monkeypatch, capsys):
        """A filter must not consume the next flag as its value."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="missingval-2")
        assert ec.main(["list", "--item", "--limit", "1"]) == 2
        assert "requires a value" in capsys.readouterr().err

    def test_list_invalid_item_value_fails_closed(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="baditem-1")
        assert ec.main(["list", "--item", "not-an-item"]) == 2
        assert "requires PREFIX-N" in capsys.readouterr().err

    def test_list_public_ref_resolves_event_filter(self, db_path, monkeypatch, capsys):
        """A complete ref selects the corresponding engine-owned event rows."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="alias-evt-1", item_id=1234)
        _insert_event(db_path, event_id="other-evt-1", item_id=9999)
        assert ec.main(["list", "--item", "YOK-1234"]) == 0
        out = capsys.readouterr().out
        assert "alias-evt-1" in out and "other-evt-1" not in out

    def test_list_rejects_bare_sequence_with_project_context(
        self,
        db_path,
        monkeypatch,
        capsys,
    ):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="alias-evt-2", item_id=2222)
        _insert_event(db_path, event_id="other-evt-2", item_id=3333)
        assert ec.main(["list", "--item", "2222", "--project", "yoke"]) == 2
        assert "public_item_ref_required" in capsys.readouterr().err

    def test_list_item_alias_rejects_bare_sequence_without_project_context(
        self,
        db_path,
        monkeypatch,
        capsys,
    ):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="alias-evt-no-project", item_id=2222)
        assert ec.main(["list", "--item", "2222"]) == 2
        assert "public_item_ref_required" in capsys.readouterr().err

    def test_list_rejects_retired_numeric_selector(self, db_path, monkeypatch, capsys):
        """The retired numeric selector is refused."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="id-evt-1", item_id=4444)
        assert ec.main(["list", "--item-id", "4444", "--project", "yoke"]) == 2
        assert "public_item_ref_required" in capsys.readouterr().err

    def test_list_limit_with_filter_is_bounded(self, db_path, monkeypatch, capsys):
        """--limit applies after filters and produces bounded output."""
        monkeypatch.setenv("YOKE_DB", db_path)
        for i in range(5):
            _insert_event(db_path, event_id=f"bnd-{i}", item_id=5555)
        assert (
            ec.main(
                [
                    "list",
                    "--item",
                    "YOK-5555",
                    "--project",
                    "yoke",
                    "--limit",
                    "2",
                ]
            )
            == 0
        )
        out = capsys.readouterr().out.strip()
        assert out and len(out.split("\n")) == 2

    def test_list_invalid_limit_fails_closed(self, db_path, monkeypatch):
        """Invalid --limit values exit 2, never produce ledger output."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="lim-bad-1")
        assert ec.main(["list", "--limit", "not-an-int"]) == 2

    def test_list_negative_limit_fails_closed(self, db_path, monkeypatch):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="lim-bad-2")
        assert ec.main(["list", "--limit", "-1"]) == 2

    def test_count_unknown_flag_fails_closed(self, db_path, monkeypatch, capsys):
        """Events count must also reject unknown flags."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path)
        assert ec.main(["count", "--bogus", "x"]) == 2
        assert "unknown filter flag" in capsys.readouterr().err

    def test_count_item_alias(self, db_path, monkeypatch, capsys):
        """Count also accepts --item alias."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="cnt-1", item_id=7000)
        _insert_event(db_path, event_id="cnt-2", item_id=7000)
        _insert_event(db_path, event_id="cnt-other", item_id=8000)
        assert ec.main(["count", "--item", "YOK-7000"]) == 0
        assert capsys.readouterr().out.strip() == "2"

    def test_anomalies_unknown_flag_fails_closed(self, db_path, monkeypatch, capsys):
        """Events anomalies must reject unknown flags."""
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["anomalies", "--bogus", "x"]) == 2
        assert "unknown filter flag" in capsys.readouterr().err

    def test_count_missing_value_fails_closed(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["count", "--item"]) == 2
        assert "requires a value" in capsys.readouterr().err
