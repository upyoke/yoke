"""Bind a candidate Command shell to its checkout and retain import evidence."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator, Mapping

from yoke_core.tools import _source_pythonpath as source


@dataclass
class CandidateSource:
    root: Path
    env: dict[str, str]
    evidence: dict = field(default_factory=dict)
    refusal: str = ""

    def inspect(self, moment: str) -> None:
        origins, reason = source.import_origins(self.root, env=self.env)
        self.evidence[moment] = origins
        if reason:
            self.refusal = (
                f"QA-CANDIDATE-IMPORT-ORIGIN REFUSAL: {reason}. "
                f"Repair the candidate checkout at {self.root} so every Yoke "
                "package resolves inside it, then rerun the same stage/member "
                "QA command. A pass cannot be recorded for outside source."
            )
            self.evidence["refusal"] = self.refusal

    def report(self) -> str:
        return "[candidate_source]\n" + json.dumps(self.evidence, sort_keys=True)


@contextmanager
def candidate_source(
    root: Path | None, env: Mapping[str, str]
) -> Iterator[CandidateSource | None]:
    """Keep the bare ``yoke`` launcher on the same Python/source as the case.

    The installed launcher can overwrite inherited PYTHONPATH. A temporary
    Python entrypoint uses the runner interpreter and the existing CLI module
    directly instead. External projects and lane cases keep their environment.
    """
    if root is None or not source.is_yoke_shaped_tree(root):
        yield None
        return
    root = root.resolve()
    with TemporaryDirectory(prefix="yoke-qa-source-") as directory:
        launcher = Path(directory) / source.YOKE_LAUNCHER_NAME
        launcher.write_text(
            f"#!{sys.executable}\n"
            "import runpy\n"
            f"runpy.run_module({source.YOKE_CLI_MODULE!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        bound = source.with_source_pythonpath(env, root)
        bound["PATH"] = directory + os.pathsep + bound["PATH"]
        binding = CandidateSource(root, bound, {"root": str(root)})
        binding.inspect("before")
        yield binding
