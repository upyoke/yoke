"""The detail read serves the sections it is asked for and indexes the rest."""

from yoke_core.domain import item_detail_read
from runtime.api.item_page_reads_test_support import _connection


def test_detail_read_indexes_content_instead_of_serving_it(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)

    assert item["narrative"] == {}
    assert item["progress_log"] is None
    index = item["content_index"]
    assert index["spec"]["read"] == "yoke items get ACM-22 spec"
    assert index["spec"]["bytes"] > 0
    assert index["spec"]["lines"] > 0
    assert index["body"] == {
        "rendered_on_demand": True,
        "read": "yoke items get ACM-22 body",
    }
    assert index["progress_log"]["read"] == (
        "yoke items section get ACM-22 --section 'Progress Log'"
    )
    # An empty stored field is not a read worth naming.
    assert "deploy_log" not in index


def test_detail_read_serves_only_the_sections_named(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51, include=["body"])

    assert set(item["narrative"]) == {"body"}
    assert "Correct the footer" in item["narrative"]["body"]
    assert item["progress_log"] is None


def test_detail_read_keeps_file_budget_when_the_spec_is_empty(monkeypatch):
    """An empty spec leaves the body the only home for the budget paths.

    The body is otherwise not rendered for a caller that did not ask for it,
    so this is the one case where the read builds it anyway.
    """
    conn = _connection()
    conn.execute("UPDATE items SET spec='' WHERE id=51")  # lint:no-lifecycle-mutation-check
    conn.execute(
        "INSERT INTO item_sections VALUES (51, 'File Budget', "
        "'- `packages/web/footer.js`', 10, 'test', 'now', 'now')"
    )
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)

    assert item["file_budget"]["paths"] == ["packages/web/footer.js"]
    assert item["narrative"] == {}
