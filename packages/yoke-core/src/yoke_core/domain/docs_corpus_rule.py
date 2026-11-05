"""Load the published public documentation file contract."""

import json
from pathlib import Path
import re

from yoke_contracts.project_contract.docs_corpus_files import CorpusRefusal

CONTRACT_PATH = Path(__file__).parents[1] / "ui/contracts/docs-corpus-files.json"


def load_corpus_rule() -> re.Pattern[str] | CorpusRefusal:
    """Refuse missing or malformed rules before inspecting corpus payloads."""
    try:
        value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or set(value) != {"schemaVersion", "allowedPathPattern", "identityFiles"}
            or type(value["schemaVersion"]) is not int
            or value["schemaVersion"] != 1
            or not isinstance(value["allowedPathPattern"], str)
            or not value["allowedPathPattern"]
            or not isinstance(value["identityFiles"], list)
            or not value["identityFiles"]
            or any(
                not isinstance(name, str) or not name or "/" in name or "\\" in name
                or name in {".", ".."}
                for name in value["identityFiles"]
            )
            or len(set(value["identityFiles"])) != len(value["identityFiles"])
        ):
            raise ValueError("invalid corpus rule schema")
        pattern = re.compile(value["allowedPathPattern"])
        identities = "|".join(re.escape(name) for name in value["identityFiles"])
        return re.compile(f"(?:{pattern.pattern}|{identities})")
    except (OSError, UnicodeError, ValueError, re.error) as exc:
        return CorpusRefusal(
            "DOCS_CORPUS_RULE_MISSING", str(CONTRACT_PATH),
            f"published corpus rule is unavailable or malformed: {exc}",
            "restore ui/contracts/docs-corpus-files.json from the matching yoke-core release",
        )
