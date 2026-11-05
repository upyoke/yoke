"""Path syntax refuses before any database read, planning or write."""

import pytest

from yoke_core.domain.path_claims_resolve import (
    PathResolveError,
    resolve_paths_to_target_ids,
    resolve_or_plan_paths_to_target_ids,
)


MALFORMED = [
    pytest.param("/etc/passwd", "path_not_project_relative", id="absolute"),
    pytest.param("../outside.py", "path_not_project_relative", id="parent-escape"),
    pytest.param(
        "docs/../secrets.py", "path_not_project_relative", id="dotdot-segment"
    ),
    pytest.param("./docs/a.py", "path_not_project_relative", id="dot-segment"),
    pytest.param("docs//a.py", "path_not_project_relative", id="empty-segment"),
    pytest.param("docs/*.py", "path_malformed", id="glob-star"),
    pytest.param("docs/a?.py", "path_malformed", id="glob-question"),
    pytest.param("'docs/a.py'", "path_malformed", id="single-quoted"),
    pytest.param('"docs/a.py', "path_malformed", id="stray-double-quote"),
    pytest.param("docs/a.py'", "path_malformed", id="trailing-quote"),
    pytest.param("docs/a\nb.py", "path_malformed", id="control-char"),
    pytest.param("docs\\a.py", "path_malformed", id="backslash"),
]


class UnusedConnection:
    def __getattr__(self, name):
        pytest.fail(f"invalid path touched database connection: {name}")


@pytest.mark.parametrize("resolve", [resolve_paths_to_target_ids, resolve_or_plan_paths_to_target_ids])
@pytest.mark.parametrize("path,code", MALFORMED)
def test_malformed_paths_refuse_before_database_access(resolve, path, code):
    with pytest.raises(PathResolveError) as caught:
        resolve(UnusedConnection(), 1, ["docs/fine.py", path])
    assert caught.value.code == code
    message = str(caught.value)
    assert repr(path)[1:-1] in message or path in message
    assert "Re-run" in message


@pytest.mark.parametrize("resolve", [resolve_paths_to_target_ids, resolve_or_plan_paths_to_target_ids])
@pytest.mark.parametrize("paths", [[], [""], ["   "]])
def test_empty_paths_refuse_before_database_access(resolve, paths):
    with pytest.raises(PathResolveError) as caught:
        resolve(UnusedConnection(), 1, paths)
    assert caught.value.code == "path_set_empty"
    assert "--paths" in str(caught.value)
