"""`yoke status` says when a universe is reachable here only, and when no
project is mapped here."""

from yoke_cli.config.status_render import LOCAL_REACH_LINE, render_human


def _report(connection, project=None):
    return {
        "ok": True,
        "connection": connection,
        "project": project or {"project_id": None, "board_scope": "all"},
    }


def test_a_local_universe_is_reachable_here_only() -> None:
    text = render_human(
        _report({"env": "local", "transport": "local-postgres", "authority_kind": ""})
    )
    assert LOCAL_REACH_LINE in text
    assert "local: reachable here only" in text


def test_a_remote_postgres_authority_is_not_called_local() -> None:
    text = render_human(
        _report(
            {
                "env": "stage-db-admin",
                "transport": "local-postgres",
                "authority_kind": "aws_aurora_postgres",
            }
        )
    )
    assert "reachable here only" not in text


def test_an_https_connection_is_not_called_local() -> None:
    text = render_human(_report({"env": "prod", "transport": "https"}))
    assert "reachable here only" not in text


def test_outside_a_project_status_says_so() -> None:
    text = render_human(_report({"env": "prod", "transport": "https"}))
    assert "  project: no project here\n" in text
    assert "id=<missing>" not in text


def test_inside_a_project_status_names_it() -> None:
    text = render_human(
        _report(
            {"env": "prod", "transport": "https"},
            {"project_id": 1, "board_scope": "1", "board_render_path": "/r/BOARD.md"},
        )
    )
    assert "  project: id=1 scope=1 board=/r/BOARD.md" in text
