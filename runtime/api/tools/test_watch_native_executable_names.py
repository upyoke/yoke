"""Native Windows interpreters still trigger nested watcher refusals."""

import pytest

from yoke_core.tools import (
    _watch_pytest_args, watch_advance, watch_doctor, watch_qa_case, watch_qa_plan,
)


@pytest.mark.parametrize("executable", [
    r"C:\Python312\python.exe", r"C:\Program Files\Python\python3.12.exe",
    "C:/Python312/python.exe", "/usr/bin/python3.12", "sys.executable",
])
@pytest.mark.parametrize(("check", "module"), [
    (_watch_pytest_args.is_nested_pytest_invocation, "pytest"),
    (watch_advance._is_nested_advance_invocation, watch_advance.UNDERLYING_MODULE),
    (watch_doctor._is_nested_doctor_invocation, "yoke_core.engines.doctor"),
    (watch_qa_case._is_nested_invocation, watch_qa_case.CASE_RUN_MODULE),
    (watch_qa_plan._is_nested_invocation, watch_qa_plan.PLAN_RUN_MODULE),
])
def test_nested_python_invocation_uses_native_executable_name(check, module, executable):
    assert check([executable, "-m", module])
    assert not check([r"C:\tools\other.exe", "-m", module])
