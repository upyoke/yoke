"""The UI server publishes the commit it is serving, or nothing.

A screenshot is only evidence about a candidate if the candidate can be
named from the screenshot's own surface. The server answers that from the
checkout its module was loaded out of — the tree the assets are read from
— and refuses to certify a working tree that carries uncommitted changes
as those committed contents.
"""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.ui import served_source_identity as identity


@pytest.fixture()
def repository(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)
    (root / "served.txt").write_text("asset\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "first"], check=True
    )
    return root


def _head(root) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_a_clean_checkout_publishes_its_commit(repository):
    assert identity.served_build(repository) == _head(repository)


def test_a_modified_tree_is_not_certified_as_its_commit(repository):
    """The failure this prevents: a screenshot of uncommitted work
    presented as evidence about a commit that does not contain it."""
    (repository / "served.txt").write_text("edited after the commit\n")

    published = identity.served_build(repository)
    assert published == f"{_head(repository)}{identity.DIRTY_SUFFIX}"
    assert published != _head(repository)


def test_an_untracked_file_also_stops_certification(repository):
    (repository / "extra.txt").write_text("not committed\n")

    assert identity.served_build(repository).endswith(identity.DIRTY_SUFFIX)


def test_a_staged_change_also_stops_certification(repository):
    (repository / "served.txt").write_text("staged\n")
    subprocess.run(["git", "-C", str(repository), "add", "-A"], check=True)

    assert identity.served_build(repository).endswith(identity.DIRTY_SUFFIX)


@pytest.mark.parametrize("root", [None, ""])
def test_no_checkout_publishes_nothing(root):
    """A packaged wheel has no serving checkout, so it names no commit —
    saying nothing is honest where inventing one is not."""
    assert identity.served_build(root) == ""


def test_a_directory_that_is_not_a_repository_publishes_nothing(tmp_path):
    assert identity.served_build(tmp_path) == ""


def test_the_packet_the_server_publishes_carries_the_serving_commit():
    """The server reads its own module origin, so the commit it publishes
    is the checkout serving the assets rather than an ambient install."""
    import json

    from yoke_core.ui.server import _local_host_identity_json

    # Unbound: no connection binding selects a control plane, so the
    # packet names no environment and the commit still has to be there.
    fields = json.loads(_local_host_identity_json(""))
    runtime = fields["runtimeIdentity"]
    if runtime.get("installKind") != "source_checkout":
        pytest.skip("this test run is not served from a source checkout")
    build = runtime.get("build", "")
    assert build, "a source checkout must publish the commit it serves"
    assert len(build.split(identity.DIRTY_SUFFIX)[0]) == 40


class TestTheServedBuildPath:
    """The commit is readable over the wire, not only inside the page.

    A reviewer reads the packet rendered into the shell; an independent
    check cannot parse a page, so the same value is published at one path
    as bare text. Both come from one resolver, because a host answering
    two different things about itself makes the cheaper answer worthless.
    """

    TOKEN = "test-session-token-value"

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient

        from yoke_core.ui import server as ui_server

        with TestClient(ui_server.create_ui_app(self.TOKEN)) as client:
            yield client

    def test_the_path_publishes_exactly_what_the_packet_publishes(self, client):
        from yoke_contracts.runtime_identity import SERVED_BUILD_PATH

        response = client.get(f"{SERVED_BUILD_PATH}?token={self.TOKEN}")

        assert response.status_code == 200
        assert response.text == identity.served_build_identity()

    def test_the_answer_is_bare_text_a_commit_matcher_can_read(self, client):
        from yoke_contracts.runtime_identity import SERVED_BUILD_PATH

        response = client.get(f"{SERVED_BUILD_PATH}?token={self.TOKEN}")

        assert response.headers["content-type"].startswith("text/plain")
        assert response.text == response.text.strip()

    def test_the_identity_path_is_not_an_opening_in_the_session_gate(
        self, client
    ):
        """The failure this prevents: publishing a read that anyone who can
        reach the port may take, on a server whose whole security model is
        that every route requires the per-run token."""
        from yoke_contracts.runtime_identity import SERVED_BUILD_PATH

        response = client.get(SERVED_BUILD_PATH)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "session_token_required"

    def test_a_stale_answer_cannot_be_served_from_a_cache(self, client):
        from yoke_contracts.runtime_identity import SERVED_BUILD_PATH

        response = client.get(f"{SERVED_BUILD_PATH}?token={self.TOKEN}")

        assert response.headers["cache-control"] == "no-store"

    def test_a_dirty_tree_is_published_as_dirty_rather_than_as_its_commit(
        self, client, monkeypatch
    ):
        """The reader matches an exact commit, so this body must fail that
        match rather than certify uncommitted work."""
        from yoke_contracts.runtime_identity import SERVED_BUILD_PATH
        from yoke_core.ui import server as ui_server

        dirty = f"{'c' * 40}{identity.DIRTY_SUFFIX}"
        monkeypatch.setattr(ui_server, "served_build_identity", lambda: dirty)

        response = client.get(f"{SERVED_BUILD_PATH}?token={self.TOKEN}")

        assert response.text == dirty
        assert len(response.text) != 40
