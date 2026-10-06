"""Doctor self scope follows the caller's canonical source checkout mapping."""

from types import SimpleNamespace

import pytest

from yoke_core.engines import doctor_context as context
from yoke_core.engines.doctor_applicability import (
    CheckApplicability,
    PROJECT_SCOPE_SELF,
    RUNTIME_LOCAL,
    not_applicable_reason,
)


@pytest.mark.parametrize("reference", ["7", "renamed"])
def test_source_identity_uses_checkout_resolver(monkeypatch, tmp_path, reference):
    monkeypatch.setattr(context, "running_source_root", lambda: tmp_path)
    monkeypatch.setattr(context, "_mapped_checkouts", lambda: [])
    monkeypatch.setattr(
        context, "is_yoke_source_checkout", lambda root: root == tmp_path
    )
    seen = []

    def mapping(root):
        seen.append(root)
        return "7"

    monkeypatch.setattr(context, "default_project_for_directory", mapping)
    monkeypatch.setattr(context, "_project_slug", lambda conn, pid: "renamed")
    monkeypatch.setattr(context, "checkout_for_project", lambda *args: None)
    monkeypatch.setattr(context, "project_capabilities", lambda *args: frozenset())
    monkeypatch.setattr(context, "resolve_https_control_plane", lambda: True)
    resolved = context.resolve_context(
        None, SimpleNamespace(project=reference), runtime=RUNTIME_LOCAL
    )
    assert seen == [tmp_path]
    assert resolved.self_project_names == {"7", "renamed"}
    assert resolved.source_checkout == tmp_path
    assert (
        not_applicable_reason(
            CheckApplicability(project_scope=PROJECT_SCOPE_SELF), resolved
        )
        is None
    )


def test_unbound_source_does_not_guess_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_PROJECT", "unrelated")
    monkeypatch.setattr(context, "running_source_root", lambda: tmp_path)
    monkeypatch.setattr(context, "_mapped_checkouts", lambda: [])
    monkeypatch.setattr(context, "is_yoke_source_checkout", lambda root: True)
    monkeypatch.setattr(context, "default_project_for_directory", lambda root: None)
    assert context.self_project_names(None) == frozenset()


def test_mapping_for_another_universe_is_not_self_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(context, "running_source_root", lambda: None)
    monkeypatch.setattr(context, "_mapped_checkouts", lambda: [(tmp_path, 7)])
    monkeypatch.setattr(context, "is_yoke_source_checkout", lambda root: True)
    monkeypatch.setattr(context, "default_project_for_directory", lambda root: None)
    assert context.self_project_names(None) == frozenset()
