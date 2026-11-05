"""Specialized command discovery and help regressions."""

from yoke_cli.commands.command_tree import immediate_children
from yoke_cli.main import main


def test_parent_help_does_not_expand_descendants(capsys):
    assert main(["items", "--help"]) == 0
    text = capsys.readouterr().out
    assert "  yoke items structured-field " in text
    assert "yoke items structured-field replace" not in text
    assert main(["onboard", "checklist", "--help"]) == 0
    text = capsys.readouterr().out
    assert "yoke onboard checklist init" in text
    assert "options:" in text


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
    assert not (tmp_path / ".yoke").exists()


def test_hyphen_split_spellings_run_but_are_not_listed_as_groups(capsys):
    assert main(["sessions", "--help"]) == 0
    text = capsys.readouterr().out
    assert "  yoke sessions end-if-empty " in text
    assert "yoke sessions end " not in text
    assert main(["sessions", "end", "--help"]) == 2
    assert "Did you mean `yoke sessions end-if-empty`?" in capsys.readouterr().err
    assert main(["sessions", "end", "if", "empty", "--help"]) == 0
    assert "usage: yoke sessions end-if-empty" in capsys.readouterr().out


def test_spaced_group_with_hyphenated_leaf_resolves(capsys):
    assert main(["github", "actions", "--help"]) == 0
    assert "  yoke github actions check-ci " in capsys.readouterr().out
    assert main(["github", "actions", "check-ci", "--help"]) == 0


def test_correlated_dispatch_is_visible_beside_one_shot_dispatch():
    children = immediate_children(("github", "actions", "workflow"))
    assert ("github", "actions", "workflow", "dispatch") in children
