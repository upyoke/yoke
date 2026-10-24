"""Settings scope routing through existing registered authority and writers."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.settings_catalog import resolve_setting

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.config import machine_config
from yoke_cli.config.runtime_settings_write import write_setting
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher


class SettingsCallError(RuntimeError):
    def __init__(self, response):
        self.response = response
        super().__init__(str(response.error))


class SettingsStore:
    def __init__(self, project=None, session_id=None):
        self.project = project
        self.session_id = session_id
        self._actor = None
        self._project_document = None
        self._machine_document = None

    def call(self, function, payload):
        if self._actor is None:
            ensure_handlers_loaded()
            self._actor = build_actor(session_id=self.session_id)
        response = call_dispatcher(
            function_id=function,
            target=TargetRef(kind="global"),
            payload=payload,
            actor=self._actor,
        )
        if not response.success:
            raise SettingsCallError(response)
        return response.result or {}

    def project_document(self):
        if self.project is None:
            raise ValueError(
                compose_refusal(
                    "settings_project_missing: select a checkout or pass --project P.",
                    recovery="yoke settings list --project P",
                )
            )
        if self._project_document is None:
            result = self.call(
                "projects.capability_settings.get",
                {"project": self.project, "cap_type": "project-policy"},
            )
            raw = result.get("settings_json") or "{}"
            self._project_document = json.loads(raw)
            if not isinstance(self._project_document, dict):
                raise ValueError(
                    compose_refusal(
                        "setting_document_invalid: project-policy must be an object.",
                        recovery="ask the project admin to repair project-policy",
                    )
                )
        return self._project_document

    def read(self, key):
        scope, spec = resolve_setting(key)
        if scope == "machine":
            if self._machine_document is None:
                self._machine_document = machine_config.load_config().get(
                    "settings", {}
                )
            document = self._machine_document
            if not isinstance(document, dict):
                raise ValueError(
                    compose_refusal(
                        "setting_document_invalid: settings must be an object.",
                        recovery="repair machine config, then retry",
                    )
                )
            present = key in document
            value = spec.stored_value(key, document[key]) if present else spec.default
            if present and key == "distribution":
                from yoke_cli.config.distribution import validate

                value = validate(**value)
        elif scope == "project":
            document = self.project_document()
            present = key in document
            value = document[key] if present else spec.default
            spec.validate(key, value)
        elif scope == "org":
            result = self.call("organizations.settings.get", {"path": key})
            value, present = result["value"], not result["defaulted"]
        else:
            result = self.call(
                "universe.levels.get"
                if key == "levels"
                else "universe.cursor_quota_order.get",
                {},
            )
            if "source" not in result:
                raise ValueError(
                    compose_refusal(
                        (
                            "settings_source_unavailable: server does not report stored/default "
                            "source; required serving floor: next-release."
                        ),
                        recovery="ask the control-plane operator to upgrade the server",
                    )
                )
            value = result["levels" if key == "levels" else "pools"]
            present = result["source"] != "default"
        row = {
            "key": key,
            "scope": scope,
            "value": value,
            "source": "stored" if present else "default",
            "meaning": spec.meaning,
            "default": spec.default,
            "type": spec.value_type.__name__,
            "minimum": spec.minimum,
            "allowed_values": spec.allowed_values,
        }

        if key == "levels" and "shipped_defaults_differ" in result:
            row["shipped_defaults_differ"] = result["shipped_defaults_differ"]
        return row

    def write(self, key, value=None, *, unset=False):
        scope, spec = resolve_setting(key)
        if not unset:
            spec.validate(key, value)
        if scope == "machine":
            write_setting(key, value, unset=unset)
            self._machine_document = None
        elif scope == "project":
            payload = {"project": self.project, "cap_type": "project-policy"}
            if unset:
                original = self.project_document()
                if key not in original:
                    return
                changed = dict(original)
                changed.pop(key, None)
                self.call(
                    "projects.capability_settings.set",
                    {
                        **payload,
                        "settings_json": json.dumps(changed),
                        "base_settings_json": json.dumps(original),
                        "create": False,
                    },
                )
            else:
                if self.project is None:
                    self.project_document()
                self.call(
                    "projects.capability_settings.merge",
                    {**payload, "assignments": {key: value}},
                )
            self._project_document = None
        elif scope == "org":
            self.call(
                "organizations.settings.merge",
                {"assignments": {key: None if unset else value}},
            )
        elif key == "levels":
            self.call(
                "universe.levels.reset" if unset else "universe.levels.set",
                {} if unset else {"levels": value},
            )
        else:
            self.call(
                "universe.cursor_quota_order.set",
                {"pools": None if unset else value},
            )
