"""Small populated read fixtures and real CLI parser discovery."""

import argparse
import json

from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from unittest.mock import patch

from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
from yoke_cli.transport.output_limit import read_output_scope


class ParserFound(Exception):
    def __init__(self, parser):
        self.parser = parser


def command_for(function):
    forms = [
        (route, adapter)
        for route, (name, adapter) in SUBCOMMAND_REGISTRY.items()
        if name == function
    ]
    return min(forms, key=lambda pair: (len(pair[0]), pair[0])) if forms else None


def parser_for(function, adapter, route):
    def capture(parser, *args, **kwargs):
        raise ParserFound(parser)

    with read_output_scope([], function, ("yoke", *route)):
        with patch.object(argparse.ArgumentParser, "parse_args", capture):
            try:
                adapter(["--help"])
            except ParserFound as found:
                return found.parser
            except SystemExit as exc:
                assert exc.code == 0
    return None


def required_args(parser):
    values = {
        "item": "TEST-99",
        "epic": "TEST-99",
        "task_num": "1",
        "project": "yoke",
        "project_id": "1",
        "head_sha": "a" * 40,
        "workflow": "dash",
        "workflow_id": "dash",
        "version": "1",
        "family": "architecture_model",
    }
    args = []
    for action in parser._actions:
        positional = not action.option_strings
        if not action.required and not (positional and action.nargs not in ("?", "*")):
            continue
        if action.option_strings:
            args.append(action.option_strings[0])
        if action.nargs != 0:
            args.append(
                values.get(
                    action.dest,
                    str(next(iter(action.choices))) if action.choices else "example",
                )
            )
    for group in parser._mutually_exclusive_groups:
        if group.required:
            action = group._group_actions[0]
            args.append(action.option_strings[0])
            if action.nargs != 0:
                args.append(values.get(action.dest, "example"))
    return args


def seed_growing_reads(conn, now):
    """Bulk inserts keep scale inexpensive; long bodies model real stored prose."""
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "SELECT 1, 'output-' || n, json_build_object('description', repeat('setting ',1000))::text, %s "
        "FROM generate_series(1,12) n",
        (now,),
    )
    conn.execute(
        "INSERT INTO strategy_docs(project_id,slug,content,updated_at) "
        "SELECT 1, 'output-' || n, repeat('strategy prose ',1000), %s "
        "FROM generate_series(1,12) n",
        (now,),
    )
    conn.execute(
        "INSERT INTO workflow_execution_instructions(content,applies_to_all_workflows,"
        "applies_to_all_projects,created_at,updated_at) "
        "SELECT 'Output instruction ' || n || chr(10) || repeat('instruction ',1000),1,1,%s,%s "
        "FROM generate_series(1,12) n",
        (now, now),
    )
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,created_at) "
        "SELECT 'output-' || n,1,'Output ' || n,repeat('flow description ',30),'[]',%s "
        "FROM generate_series(1,12) n",
        (now,),
    )
    # Copy valid pinned definitions rather than inventing a second workflow schema.
    conn.execute(
        "INSERT INTO workflows(id,name,description,source,current_version_id,created_at,updated_at) "
        "SELECT 'output-' || n,'Output ' || n,repeat('workflow description ',1000),'project',"
        "NULL,%s,%s FROM generate_series(1,12) n",
        (now, now),
    )
    conn.execute(
        "INSERT INTO workflow_versions(id,workflow_id,version,definition_schema_version,"
        "definition_json,definition_digest,published_at,immutable_at,published_reason) "
        "SELECT 10000+n,'output-' || n,1,v.definition_schema_version,v.definition_json,"
        "v.definition_digest,%s,%s,repeat('publication reason ',1000) "
        "FROM generate_series(1,12) n CROSS JOIN LATERAL "
        "(SELECT * FROM workflow_versions ORDER BY id LIMIT 1) v",
        (now, now),
    )
    conn.execute(
        "UPDATE workflows SET current_version_id=10000+substring(id from 8)::integer "
        "WHERE id LIKE 'output-%%'"
    )
    raw = conn.execute(
        "SELECT definition_json FROM workflow_versions WHERE workflow_id='dash' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    for index in range(30):
        definition = json.loads(raw)
        definition["stages"][0]["label"] = f"Output stage {index}"
        conn.execute(
            "INSERT INTO workflow_versions(id,workflow_id,version,definition_schema_version,"
            "definition_json,definition_digest,published_at,immutable_at,published_reason) "
            "VALUES(%s,'dash',%s,%s,%s,%s,%s,%s,%s)",
            (
                20000 + index,
                100 + index,
                definition["schema_version"],
                canonical_definition_json(definition),
                definition_digest(definition),
                now,
                now,
                "publication reason " * 30,
            ),
        )
