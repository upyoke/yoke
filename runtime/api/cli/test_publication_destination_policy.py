"""Read-only Yoke policy must survive setup, work entry, and governed pushes."""

from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import credentialed_git, project_onboard, project_clone_support
from yoke_cli.config import project_publication_destination as destination
from yoke_cli.config import onboard_publication
from yoke_cli.project_install import publication_eligibility, publication_commit_ownership
from yoke_core.domain import worktree_preflight_upstream


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ['git', '-C', str(root), *args], check=True,
        capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    source = tmp_path / 'source.git'
    source.mkdir()
    git(source, 'init', '--bare', '--initial-branch=main')
    root = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', str(source), str(root)], check=True,
                   capture_output=True)
    git(root, 'config', 'user.email', 'test@example.com')
    git(root, 'config', 'user.name', 'Test')
    (root / 'README').write_text('source\n')
    git(root, 'add', 'README')
    git(root, 'commit', '-m', 'source')
    git(root, 'push', 'origin', 'main')
    from runtime.api.cli.test_project_publication_settings import seed_project

    seed_project(root)
    return root, source


@pytest.mark.parametrize('reused', [False, True])
def test_read_only_preserves_fetch_and_refuses_all_publication(checkout, monkeypatch, reused):
    root, source = checkout
    original = git(source, 'rev-parse', 'main')
    outcome = project_onboard._apply_clone_outcome(
        root, remote_url=str(source), default_branch='main',
        plan=project_clone_support.ClonePlan(), clone_reused=reused,
    )
    assert outcome.publication_read_only
    before = (root / ".git/config").read_bytes()
    destination.prevent_push(root)
    assert (root / ".git/config").read_bytes() == before
    assert git(root, 'remote', 'get-url', 'origin') == str(source)
    git(root, 'fetch', 'origin')
    (root / 'work').write_text('must stay local\n')
    git(root, 'add', 'work')
    git(root, 'commit', '-m', 'local work')
    blocked = credentialed_git.run(['-C', str(root), 'push', 'origin', 'main'])
    assert blocked.returncode != 0
    assert 'publication_destination_read_only' in blocked.stderr
    assert git(source, 'rev-parse', 'main') == original
    outcome = publication_eligibility.push_eligibility(
        root, branch='main', remote='origin',
        territory=publication_commit_ownership.InstallerTerritory(),
    )
    assert outcome['status'] == 'publication_pending'
    assert 'publication_destination_read_only' in outcome['recovery']
    monkeypatch.setattr(worktree_preflight_upstream, 'refresh_base_branch',
                        lambda *_: pytest.fail('must refuse before work/fetch'))
    gate = worktree_preflight_upstream.gate_upstream_for_preparation(
        str(root), {'project': {'default_branch': 'main'}}, no_worktree=False,
    )
    assert gate.block_kind == 'publication_destination_read_only'
    assert 'writable' in gate.narrative


def test_explicit_source_selection_restores_push_without_changing_fetch(checkout):
    root, source = checkout
    destination.prevent_push(root)
    outcome = project_onboard._apply_clone_outcome(
        root, remote_url=str(source), default_branch='main',
        plan=project_clone_support.ClonePlan(outcome=project_clone_support.CLONE_OUTCOME_SOURCE),
    )
    assert not outcome.publication_read_only
    destination.allow_source_push(root)
    assert not destination.read_only(root)
    assert git(root, 'remote', 'get-url', 'origin') == str(source)
    (root / 'work').write_text('owned destination\n')
    git(root, 'add', 'work')
    git(root, 'commit', '-m', 'owned work')
    git(root, 'push', 'origin', 'main')
    assert git(source, 'rev-parse', 'main') == git(root, 'rev-parse', 'HEAD')


def test_read_only_review_does_not_offer_credential_fallback(checkout, tmp_path):
    root, source = checkout
    step = onboard_publication.plan_step({
        'checkout': str(root), 'remote_url': str(source), 'default_branch': 'main',
        'clone': project_clone_support.ClonePlan(),
    }, tmp_path / 'config.json')
    assert 'Yoke publication disabled' in step['target']
    assert 'publication pending' in step['target']
    assert 'try to push' not in step['target']


def test_fork_without_authorization_does_not_silently_keep_source(checkout):
    root, source = checkout
    with pytest.raises(project_onboard.ProjectOnboardError, match='publication_destination_unresolved'):
        project_onboard._apply_clone_outcome(
            root, remote_url=str(source), default_branch='main',
            plan=project_clone_support.ClonePlan(outcome=project_clone_support.CLONE_OUTCOME_FORK),
        )
    assert git(root, 'remote', 'get-url', 'origin') == str(source)


def test_independent_adoption_uses_shared_destination_applier(checkout, tmp_path, monkeypatch):
    from yoke_cli.config import onboard_project
    from yoke_cli.config.onboard_wizard import WizardResult

    root, source = checkout
    result = WizardResult(
        env_name="prod", api_url="", config_path=str(tmp_path / "config.json"),
        project_mode=onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        project_checkout=str(root), project_remote_url=str(source),
        project_clone_outcome=project_clone_support.CLONE_OUTCOME_JUST_CLONE,
    )
    plan = result.build_clone_plan()
    calls = []
    monkeypatch.setattr(onboard_project.project_onboard, 'import_project',
                        lambda **kwargs: calls.append(kwargs) or {'status': 'preview'})
    onboard_project.project_report(
        config_path=tmp_path / 'config.json', apply=False,
        inputs={'mode': result.project_mode, 'checkout': str(root),
                'remote_url': str(source), 'clone': plan, 'slug': 'owned',
                'name': 'Owned', 'default_branch': 'main', 'public_item_prefix': 'OWN'},
    )
    assert calls[0]['clone'].outcome == project_clone_support.CLONE_OUTCOME_JUST_CLONE
    assert calls[0]['remote_url'] == str(source)


def test_duplicate_refuses_unrelated_local_commit_before_creation(checkout, monkeypatch):
    from yoke_cli.config import github_publish
    from yoke_cli.config.project_publish_support import PublishRequest

    root, source = checkout
    (root / 'unpublished').write_text('operator work\n')
    git(root, 'add', 'unpublished')
    git(root, 'commit', '-m', 'unpublished operator work')
    monkeypatch.setattr(github_publish, 'create_repo',
                        lambda *_a, **_k: pytest.fail('must refuse before creating'))
    plan = project_clone_support.ClonePlan(
        outcome=project_clone_support.CLONE_OUTCOME_MAKE_IT_MINE,
        publish=PublishRequest(owner='owned', name='copy', user_login='owned', token='test'),
    )
    with pytest.raises(project_onboard.ProjectOnboardError, match='publication_source_unverified'):
        project_onboard._apply_clone_outcome(
            root, remote_url=str(source), default_branch='main', plan=plan,
        )
    assert git(root, 'remote', 'get-url', 'origin') == str(source)


def test_governed_merge_refuses_read_only_before_integration(checkout):
    from types import SimpleNamespace
    from yoke_core.engines.merge_worktree_prepare_preflight import preflight_checks

    root, source = checkout
    original = git(root, 'rev-parse', 'HEAD')
    destination.prevent_push(root)
    code, message = preflight_checks(SimpleNamespace(repo_root=str(root)))
    assert code != 0
    assert 'publication_destination_read_only' in message
    native_push = subprocess.run(['git', '-C', str(root), 'push', 'origin', 'main'],
                                 capture_output=True, text=True)
    assert native_push.returncode == 0
    assert git(source, 'rev-parse', 'main') == original


def test_saved_read_only_setup_reopens_destination_without_remote_mutation(checkout, tmp_path):
    from yoke_cli.config.onboard_wizard import WizardResult
    from yoke_cli.config.onboard_wizard_project_identity_flow import ProjectIdentityFlow

    root, source = checkout
    destination.prevent_push(root)

    class Shell(ProjectIdentityFlow):
        result = WizardResult(
            env_name='prod', api_url='', config_path=str(tmp_path / 'config.json'),
            project_checkout=str(root), existing_project_id=77,
        )
        offered = False

        def _goto_clone_outcome(self):
            self.offered = True

    shell = Shell()
    shell._after_existing_project_ready()
    assert shell.offered
    assert shell.result.project_remote_url == str(source)
    assert shell.result.project_clone_existing_layer_decision == 'keep'
    assert destination.read_only(root)
    assert git(root, 'remote', 'get-url', 'origin') == str(source)


def test_changed_source_refuses_before_read_only_configuration(checkout):
    root, source = checkout
    git(root, 'remote', 'set-url', 'origin', str(source.parent / 'different.git'))
    with pytest.raises(project_onboard.ProjectOnboardError, match='publication_destination_changed'):
        project_onboard._apply_clone_outcome(
            root, remote_url=str(source), default_branch='main',
            plan=project_clone_support.ClonePlan(),
        )
    assert not destination.read_only(root)


@pytest.mark.parametrize("remote", ["origin", "upstream"])
def test_legacy_policy_migrates_once_without_changing_real_remote_urls(checkout, remote):
    root, source = checkout
    if remote == "upstream":
        git(root, "remote", "add", "upstream", str(source))
    git(root, "config", "--add", f"remote.{remote}.pushurl", destination.LEGACY_READ_ONLY_PUSH_URL)
    git(root, "config", "--add", f"remote.{remote}.pushurl", str(source))
    destination.migrate_legacy(root)
    assert destination.read_only(root) is (remote == "origin")
    assert git(root, "remote", "get-url", "--push", "--all", remote) == str(source)
    after = (root / ".git/config").read_bytes()
    assert destination.read_only(root) is (remote == "origin")
    assert (root / ".git/config").read_bytes() == after
    assert git(root, "remote", "get-url", remote) == str(source)


def test_yoke_push_to_explicit_url_cannot_bypass_project_setting(checkout):
    root, source = checkout
    destination.prevent_push(root)
    result = credentialed_git.run(["-C", str(root), "push", str(source), "main"])
    assert result.returncode != 0
    assert "publication_destination_read_only" in result.stderr


def test_linked_lane_inherits_primary_checkout_setting(checkout):
    root, _ = checkout
    lane = root.parent / "lane"
    git(root, "worktree", "add", "-b", "topic", str(lane))
    destination.prevent_push(root)
    assert destination.read_only(lane)


def test_failed_policy_persistence_preserves_legacy_git_guard(checkout, monkeypatch):
    from yoke_cli.config import writer_projects

    root, _ = checkout
    git(root, "config", "remote.origin.pushurl", destination.LEGACY_READ_ONLY_PUSH_URL)
    before = (root / ".git/config").read_bytes()

    def fail(*args, **kwargs):
        raise OSError("config unavailable")

    monkeypatch.setattr(writer_projects, "set_publication_read_only", fail)
    with pytest.raises(OSError, match="config unavailable"):
        destination.migrate_legacy(root)
    assert (root / ".git/config").read_bytes() == before


def test_legacy_policy_read_never_mutates_config(checkout, monkeypatch):
    from yoke_cli.config import machine_config, writer_projects

    root, _ = checkout
    git(root, "config", "remote.origin.pushurl", destination.LEGACY_READ_ONLY_PUSH_URL)
    git_before = (root / ".git/config").read_bytes()
    config = machine_config.config_path()
    config_before = config.read_bytes()
    monkeypatch.setattr(writer_projects, "set_publication_read_only",
                        lambda *a, **kw: pytest.fail("policy reads must not write"))
    assert destination.read_only(root)
    assert destination.read_only(root)
    assert (root / ".git/config").read_bytes() == git_before
    assert config.read_bytes() == config_before
