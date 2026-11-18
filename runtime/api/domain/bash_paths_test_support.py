"""An explicit POSIX executing client, independent of the authority's OS."""

import pytest
from yoke_contracts.hook_runner.bash_paths import client_path_scope


@pytest.fixture
def posix_client_paths():
    with client_path_scope({"windows": False, "home": "", "canonical": {}}):
        yield
