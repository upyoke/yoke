"""Every supported help spelling is bounded, discoverable and inert."""

import contextlib
import io
import json
from pathlib import Path

from yoke_cli.commands.command_tree import discovery_routes, immediate_children
from yoke_cli.commands.group_help import can_route_group
from yoke_cli.main import main
from yoke_cli.transport.response_evidence import wrapped_lines


def test_all_help_routes_are_inert_and_bounded(monkeypatch, tmp_path):
    def deny(*args, **kwargs):
        raise AssertionError("Help attempted execution or network access")

    monkeypatch.setattr("subprocess.Popen", deny)
    monkeypatch.setattr("socket.socket.connect", deny)
    monkeypatch.setattr(Path, "write_text", deny)
    monkeypatch.setattr(
        "yoke_cli.commands.adapters.source_dev_run._source_runner", deny
    )
    evidence = []
    routes = discovery_routes()
    prefixes = {route[:n] for route in routes for n in range(1, len(route))}
    for route in sorted(set(routes) | prefixes | {()}):
        flags = ("--help", "-h", "help") if can_route_group(route) else ("--help", "-h")
        for flag in flags:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = main([*route, flag])
            text = out.getvalue() + err.getvalue()
            record = dict(
                route="yoke " + " ".join(route),
                flag=flag,
                exit=rc,
                lines=wrapped_lines(text),
                characters=len(text),
                advisory_lines=40
                if not route
                else 80
                if can_route_group(route)
                else 120,
            )
            evidence.append(record)
            assert rc == 0, (record, text)
            assert text.strip(), record
            assert record["lines"] <= 350, (record, text)
            for child in immediate_children(route):
                assert "yoke " + " ".join(child) in text, (record, child)
            assert "bad/missing flag" not in text
    # Audit evidence is a fixture report, never a claim of live execution.
    with (tmp_path / "help-routes.json").open("w") as handle:
        json.dump(evidence, handle)
    print(
        f"Fixture help audit: {len(evidence)} spellings; max lines "
        f"{max(row['lines'] for row in evidence)}; advisory overruns "
        f"{sum(row['lines'] > row['advisory_lines'] or row['characters'] > row['advisory_lines'] * 60 for row in evidence)}"
    )
    for row in evidence:
        if (
            row["lines"] > row["advisory_lines"]
            or row["characters"] > row["advisory_lines"] * 60
        ):
            print("Advisory review:", row)


def test_parent_help_does_not_expand_descendants(capsys):
    assert main(["items", "--help"]) == 0
    text = capsys.readouterr().out
    assert "yoke items structured-field  --help" in text
    assert "yoke items structured-field replace" not in text
    assert main(["onboard", "checklist", "--help"]) == 0
    text = capsys.readouterr().out
    assert "yoke onboard checklist init" in text
    assert "options:" in text


def test_strategy_doc_help_names_the_link_that_moves_an_item(capsys):
    link = "yoke strategy execution link ITEM --project P --slug SLUG"
    assert main(["strategy", "doc", "--help"]) == 0
    assert link in capsys.readouterr().out
    try:
        main(["dash", "--help"])
    except SystemExit:
        pass
    assert link in " ".join(capsys.readouterr().out.split())


def test_root_contains_convenience_routes(capsys):
    assert main(["help"]) == 0
    text = capsys.readouterr().out
    assert "yoke dash " in text
    assert "yoke task " in text
    assert "yoke items create" not in text


def test_no_project_help_has_a_reference_without_installing(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    assert main(["--help"]) == 0
    text = capsys.readouterr().out
    assert "Without a project: https://upyoke.com/docs" in text
    assert "Installed project: /yoke help" in text
    assert not (tmp_path / ".yoke").exists()
