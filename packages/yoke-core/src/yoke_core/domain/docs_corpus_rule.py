"""Load the published public documentation file contract."""

import json
from pathlib import Path
import re

from yoke_contracts.project_contract.docs_corpus_files import CorpusRefusal

CONTRACT_PATH = Path(__file__).parents[1] / "ui/contracts/docs-corpus-files.json"


def _load_contract() -> dict | CorpusRefusal:
    """Refuse missing or malformed rules before inspecting corpus payloads."""
    try:
        value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or set(value) != {"schemaVersion", "allowedPathPattern", "identityFiles", "assetRules"}
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
        re.compile(value["allowedPathPattern"])
        assets = value["assetRules"]
        if (
            not isinstance(assets, dict)
            or set(assets) != {"allowedElements", "refusedStyleTextPattern"}
            or not isinstance(assets["allowedElements"], dict)
            or set(assets["allowedElements"]) != {"svg", "html"}
            or any(
                not isinstance(tags, list) or not tags
                or any(not isinstance(tag, str) or not re.fullmatch(r"[a-z][a-z0-9:-]*", tag) for tag in tags)
                or len(set(tags)) != len(tags)
                for tags in assets["allowedElements"].values()
            )
            or not isinstance(assets["refusedStyleTextPattern"], str)
            or not assets["refusedStyleTextPattern"]
        ):
            raise ValueError("invalid asset rule schema")
        re.compile(assets["refusedStyleTextPattern"], re.IGNORECASE)
        return value
    except (OSError, UnicodeError, ValueError, re.error) as exc:
        return CorpusRefusal(
            "DOCS_CORPUS_RULE_MISSING", str(CONTRACT_PATH),
            f"published corpus rule is unavailable or malformed: {exc}",
            "restore ui/contracts/docs-corpus-files.json from the matching yoke-core release",
        )


def load_corpus_rule() -> re.Pattern[str] | CorpusRefusal:
    """Read the file allowlist from the published contract."""
    value = _load_contract()
    if isinstance(value, CorpusRefusal):
        return value
    identities = "|".join(re.escape(name) for name in value["identityFiles"])
    return re.compile(f"(?:{value['allowedPathPattern']}|{identities})")


def load_asset_rule() -> dict | CorpusRefusal:
    """Read the element and style rules shared with the hosted docs consumer."""
    value = _load_contract()
    return value if isinstance(value, CorpusRefusal) else value["assetRules"]
