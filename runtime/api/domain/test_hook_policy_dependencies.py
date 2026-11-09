"""Keep policy evaluation below the hook runtime and pure validation isolated."""

from pathlib import Path

from yoke_contracts.path_source_scan import extract_edges

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / 'packages/yoke-core/src/yoke_core'
PURE_HOOKS = {
    'yoke_core.hooks.types',
    'yoke_core.hooks.decision_render',
    'yoke_core.hooks.hook_context_compose',
    'yoke_core.hooks.turn_end_decision_render',
}


def _imports(path):
    scan = extract_edges(path.read_text(), path.relative_to(ROOT).as_posix())
    assert scan.error is None, scan.error
    return {edge['imported_module'] for edge in scan.edges}


def test_policies_import_only_pure_hook_surfaces():
    violations = []
    for pattern in ('lint_*.py', 'hint_*.py'):
        for path in (CORE / 'domain').glob(pattern):
            for module in _imports(path):
                if module.startswith('yoke_core.hooks') and module not in PURE_HOOKS:
                    violations.append((path.name, module))
    assert violations == []


def test_pure_hook_surfaces_depend_only_on_contracts_and_each_other():
    for module in PURE_HOOKS:
        path = CORE / (module.removeprefix('yoke_core.').replace('.', '/') + '.py')
        assert {
            name for name in _imports(path)
            if name.startswith('yoke_') and not name.startswith('yoke_contracts.')
        } <= PURE_HOOKS


def test_architecture_validators_do_not_depend_on_domain_runtime():
    allowed = {
        'yoke_core.domain.architecture_model_sections',
        'yoke_core.domain.architecture_model_derive',
    }
    for path in (CORE / 'domain').glob('architecture_model*.py'):
        assert {name for name in _imports(path) if name.startswith('yoke_core.')} <= allowed


PURE_CHECKS = {
    'lint_command_extract',
    'lint_config_report',
    'lint_db_rules_executed_sql',
    'lint_destructive_git_commands',
    'lint_item_ref_bare_cli_token',
    'lint_item_ref_construction',
    'lint_item_ref_message_text',
    'lint_long_command_polling_constants',
    'lint_long_command_polling_decide',
    'lint_long_command_polling_test_helpers',
    'lint_main_commit_client_facts',
    'lint_no_agent_runtime_api_import_from_c_messages',
    'lint_no_agent_runtime_api_import_from_c_readonly',
    'lint_project_name_literal',
    'lint_project_name_literal_allowances',
    'lint_python_heredoc_sources',
    'lint_runtime_hosts',
    'lint_session_bound_yoke_commands',
    'lint_session_cwd_gh_repo_selector',
    'lint_session_cwd_git_read_forms',
    'lint_session_cwd_home',
    'lint_session_cwd_host_command',
    'lint_session_cwd_remote_resources',
    'lint_session_cwd_wrapped_remote_argv',
    'lint_shell_script_arguments',
    'lint_shell_target_tokens',
    'lint_shell_write_operands',
    'lint_structured_field_transform_shell_messages',
    'lint_subagent_background_constants',
    'lint_subagent_background_decide',
    'lint_workspace_repo_root_scan',
    'lint_yoke_adapter_output_truncation',
    'lint_yoke_quoted_shell_substitution_messages',
}


def test_named_pure_checks_stay_below_policy_evaluation():
    allowed = PURE_HOOKS | {"yoke_core.domain." + name for name in PURE_CHECKS}
    for name in PURE_CHECKS:
        path = CORE / "domain" / (name + ".py")
        assert "HookDecision" not in path.read_text()
        assert {module for module in _imports(path) if module.startswith("yoke_core.")} <= allowed
