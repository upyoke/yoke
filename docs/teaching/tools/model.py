"""Load, cross-check and canonically format the teaching prototype model.

Every model file is JSON under ``docs/teaching/model``. Loading never stops
at the first defect: each problem is collected with the file and record it
names, so one check run reports everything that needs repair.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

TEACHING_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = TEACHING_ROOT / "model"
STATUSES = (
    "observed",
    "verified-live",
    "candidate",
    "approved",
    "deferred",
    "draft-copy",
    "superseded",
)
RETIRED_PLAN_MIRROR = (
    "strategy documents are not mirrored here; move any lasting teaching fact "
    "into a scenario, surface, boundary or gap record"
)
REBUILD = "yoke dev run -- python3 docs/teaching/tools/build.py"


@dataclass(frozen=True)
class Problem:
    code: str
    where: str
    message: str

    def render(self) -> str:
        return f"{self.code}: {self.where}: {self.message}"


@dataclass
class Model:
    concepts: dict = field(default_factory=dict)
    concept_files: list = field(default_factory=list)
    surfaces: dict = field(default_factory=dict)
    teaching: dict = field(default_factory=dict)
    scenarios: dict = field(default_factory=dict)
    lessons: dict = field(default_factory=dict)
    evidence_files: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    boundaries: dict = field(default_factory=dict)
    gaps: dict = field(default_factory=dict)
    docs_graph: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)

    def problem(self, code: str, where: str, message: str) -> None:
        self.problems.append(Problem(code, where, message))


def dump(value) -> str:
    """Canonical model text: one-space indent, scalar lists kept inline."""
    return _format(value, 0) + "\n"


def _format(value, depth: int) -> str:
    pad = " " * depth
    if isinstance(value, dict) and value:
        items = [
            f"{pad} {json.dumps(key, ensure_ascii=False)}: {_format(item, depth + 1)}"
            for key, item in value.items()
        ]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value):
        items = [f"{pad} {_format(item, depth + 1)}" for item in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def model_files() -> list[Path]:
    return sorted(MODEL_ROOT.rglob("*.json"))


def relative(path: Path) -> str:
    return path.relative_to(TEACHING_ROOT.parents[1]).as_posix()


def _read(model: Model, path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        model.problem("MODEL_UNREADABLE", relative(path), f"{error}; fix the JSON")
        return None


def _register(
    model: Model, table: dict, record_id: str, record: dict, where: str
) -> None:
    if record_id in table:
        model.problem("DUPLICATE_ID", where, f"id {record_id!r} is defined twice")
    record["file"] = where
    table[record_id] = record


def _records(model: Model, directory: Path):
    records = []
    for path in sorted(directory.glob("*.json")):
        data = _read(model, path)
        if data is None:
            continue
        if not isinstance(data, dict) or data.get("id") != path.stem:
            model.problem(
                "MODEL_RECORD_ID",
                relative(path),
                "store one record whose id matches the filename",
            )
            continue
        records.append((path, data))
    return sorted(records, key=lambda pair: pair[1].get("position", 0))


def load() -> Model:
    model = Model()
    concept_root = MODEL_ROOT / "concepts"
    directories = sorted(
        [concept_root, *[p for p in concept_root.rglob("*") if p.is_dir()]],
        key=lambda p: (len(p.parts), p.as_posix()),
    )
    pages = {}
    for directory in directories:
        parent = directory.relative_to(concept_root).as_posix()
        parent = None if parent == "." else parent
        for path, record in _records(model, directory):
            full = f"{parent}/{record['id']}" if parent else record["id"]
            page = record.get("page", full.split("/")[0])
            record.update(full_id=full, parent=parent, page=page, children=[])
            _register(model, model.concepts, full, record, relative(path))
            if parent is not None:
                if parent not in model.concepts:
                    model.problem(
                        "DANGLING_PARENT",
                        relative(path),
                        f"parent {parent!r} is missing; add its record",
                    )
                    continue
                model.concepts[parent]["children"].append(full)
            if parent is None or model.concepts[parent]["page"] != page:
                entry = pages.setdefault(
                    page, {"stem": page, "parent": parent, "roots": []}
                )
                entry["roots"].append(full)
    model.concept_files = sorted(
        pages.values(), key=lambda p: (p["parent"] is not None, p["stem"])
    )
    for kind, owners, parts in (
        ("surfaces", model.surfaces, model.teaching),
        ("scenarios", model.scenarios, model.lessons),
    ):
        for path, owner in _records(model, MODEL_ROOT / kind):
            owner.update(page=path.stem, parts=[])
            _register(model, owners, owner["id"], owner, relative(path))
            for child_path, record in _records(model, path.with_suffix("")):
                full = f"{owner['id']}/{record['id']}"
                record.update(full_id=full, owner=owner["id"], page=path.stem)
                _register(model, parts, full, record, relative(child_path))
                owner["parts"].append(full)
    for path, group in _records(model, MODEL_ROOT / "evidence"):
        group.update(stem=path.stem, records=[])
        model.evidence_files.append(group)
        for child_path, record in _records(model, path.with_suffix("")):
            record["page"] = path.stem
            record_id = f"{path.stem}/{record['id']}"
            _register(model, model.evidence, record_id, record, relative(child_path))
            group["records"].append(record)
    if (MODEL_ROOT / "plan").exists():
        model.problem(
            "RETIRED_PLAN_MIRROR", "docs/teaching/model/plan", RETIRED_PLAN_MIRROR
        )
    for kind, table in (("boundaries", model.boundaries), ("gaps", model.gaps)):
        for path, record in _records(model, MODEL_ROOT / kind):
            _register(model, table, record["id"], record, relative(path))
    model.docs_graph = _read(model, MODEL_ROOT / "docs-graph.json") or {}
    return model


def all_records(model: Model):
    """Yield ``(kind, id, record)`` for every record that carries a status."""
    for kind, table in (
        ("concept", model.concepts),
        ("surface", model.surfaces),
        ("teaching", model.teaching),
        ("scenario", model.scenarios),
        ("lesson", model.lessons),
        ("boundary", model.boundaries),
        ("gap", model.gaps),
        ("evidence", model.evidence),
    ):
        for record_id, record in table.items():
            yield kind, record_id, record


def validate(model: Model, live: dict, repo_files: set) -> None:
    """Check statuses, references and cited source paths.

    ``live`` maps ``commands``, ``functions`` and ``skills`` to the sets the
    live registries expose; ``repo_files`` is the git-tracked path set.
    """
    targets = {
        "surface_refs": model.surfaces,
        "concepts": model.concepts,
        "topics": model.concepts,
        "surfaces": model.surfaces,
        "scenarios": model.scenarios,
        "related_scenarios": model.scenarios,
        "boundaries": model.boundaries,
        "gaps": model.gaps,
        "related": model.concepts,
        "commands": live["commands"],
        "functions": live["functions"],
        "skills": live["skills"],
    }
    for kind, record_id, record in all_records(model):
        where = f"{record.get('file', '?')}:{record_id}"
        status = record.get("status")
        if status not in STATUSES:
            model.problem(
                "UNKNOWN_STATUS",
                where,
                f"status {status!r} is not one of {', '.join(STATUSES)}",
            )
        for key, table in targets.items():
            values = record.get(key)
            for value in [values] if isinstance(values, str) else values or []:
                if value not in table:
                    origin = (
                        "live registry"
                        if key in ("commands", "functions", "skills")
                        else "model"
                    )
                    model.problem(
                        "DANGLING_REFERENCE",
                        where,
                        f"{key} names {value!r}, absent from the {origin}",
                    )
        for source in record.get("sources", []):
            path = (
                source.rsplit(":", 1)[0]
                if source.rsplit(":", 1)[-1].isdigit()
                else source
            )
            if path not in repo_files:
                model.problem(
                    "DANGLING_SOURCE",
                    where,
                    f"source {source!r} is not a tracked repository file",
                )
        if "plan_refs" in record:
            model.problem(
                "RETIRED_PLAN_MIRROR", where, f"remove plan_refs; {RETIRED_PLAN_MIRROR}"
            )
    for area in model.docs_graph.get("areas", []):
        for concept in area.get("concepts", []):
            if concept not in model.concepts:
                model.problem(
                    "DANGLING_REFERENCE",
                    f"docs-graph.json:{area['id']}",
                    f"concepts names {concept!r}, absent from the model",
                )


def coverage(model: Model) -> dict:
    """Return concept id -> sorted teaching ids that name it as a topic.

    Only direct mappings count: a mapped parent never covers its children.
    """
    mapped = {concept_id: set() for concept_id in model.concepts}
    for teaching_id, record in model.teaching.items():
        for concept_id in record.get("topics", []):
            mapped.get(concept_id, set()).add(teaching_id)
    return {concept_id: sorted(ids) for concept_id, ids in mapped.items()}
