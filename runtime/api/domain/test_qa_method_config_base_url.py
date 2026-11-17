"""Command URL declarations match whole identifiers across command languages."""

import pytest

from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)


@pytest.mark.parametrize(
    "command",
    [
        "echo $YOKE_PROD_DISTRIBUTION_BASE_URL",
        "echo $NODE_DIST_BASE_URL",
        "echo $BASE_URLS",
    ],
)
def test_longer_identifiers_need_no_base_url_declaration(command):
    assert validate_method_config("command", {"command": command}) == {
        "command": command
    }


@pytest.mark.parametrize(
    "command",
    [
        "curl $BASE_URL",
        "curl ${BASE_URL}",
        'curl "$BASE_URL/health"',
        "python3 -c 'import os; print(os.environ[\"BASE_URL\"])'",
        "node -e 'console.log(process.env.BASE_URL)'",
    ],
)
@pytest.mark.parametrize("declaration", [None, False, True])
def test_whole_base_url_identifier_requires_declaration(command, declaration):
    config = {"command": command}
    if declaration is not None:
        config["requires_base_url"] = declaration
    if declaration is True:
        assert validate_method_config("command", config) == config
    else:
        with pytest.raises(QaMethodConfigError, match="reads BASE_URL"):
            validate_method_config("command", config)
