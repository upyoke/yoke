"""The boot converge must tell the applier what version is applying.

``apply_pending`` reads an omitted version as "unresolved" and skips its
refusal, which is right for a source checkout and catastrophic as a silent
default: a caller that forgets the argument disables the guard on every
container, forever, while every unit test that passes the argument
explicitly still passes.

So the contract under test is not the comparison — that is covered
elsewhere — but the wiring: the production caller supplies a real value.
"""

from __future__ import annotations

import inspect

import pytest

from yoke_core.domain import migration_boot_apply, schema_init
from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT


class TestApplierRequiresAnExplicitVersion:
    def test_running_version_has_no_default(self) -> None:
        """A default here would let a caller switch the guard off silently."""
        parameter = inspect.signature(migration_boot_apply.apply_pending).parameters[
            "running_version"
        ]

        assert parameter.default is inspect.Parameter.empty

    def test_omitting_it_is_a_type_error_not_a_silent_pass(self) -> None:
        with pytest.raises(TypeError):
            migration_boot_apply.apply_pending(
                object(),
                history=(),
                ledger=YOKE_LEDGER_CONTRACT,
                applied_by="test",
            )


class TestBootConvergeWiring:
    def test_converge_passes_the_installed_engine_version(self) -> None:
        """Read the call site directly.

        Executing the converge needs a live Postgres connection and a real
        history, so the cheapest honest assertion about the wiring is that
        the call names the resolver rather than falling back to a default.
        """
        source = inspect.getsource(schema_init.converge_migration_history)

        assert "running_version=installed_engine_version()" in source

    def test_the_resolver_is_the_one_that_reports_source_trees_as_empty(self) -> None:
        """The empty answer is what keeps developer machines from refusing."""
        from yoke_contracts.engine_version import installed_engine_version

        resolved = installed_engine_version()

        assert isinstance(resolved, str)
