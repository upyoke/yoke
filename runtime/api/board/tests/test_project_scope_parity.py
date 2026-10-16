"""Project scope uses bound parameters."""

from yoke_contracts.board.project_scope import project_filter


def test_project_scope_changes_parameters_not_query_shape():
    first_sql, first_params = project_filter("yoke", "i")
    second_sql, second_params = project_filter("externalwebapp", "i")

    assert first_sql == second_sql
    assert first_params == ("yoke",)
    assert second_params == ("externalwebapp",)
    assert "yoke" not in first_sql
    assert "externalwebapp" not in second_sql
