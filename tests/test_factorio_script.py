from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "tools" / "factorio_script.py"
    spec = importlib.util.spec_from_file_location("_test_factorio_script", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _payload(result):
    assert result.success is True
    return json.loads(result.output)


def test_capabilities_lists_structured_primitives():
    module = _load_module()

    payload = _payload(module.factorio_script("system.capabilities"))

    assert "read.tick" in payload["names"]
    assert "action.build_iron_plate_line" in payload["names"]
    assert "wait.seconds" in payload["names"]


def test_runs_named_lua_script_through_rcon_helper(monkeypatch):
    module = _load_module()
    calls = []

    class FakeHelper:
        @staticmethod
        def build_command(script_name, lua, args):
            calls.append((script_name, args, "return" in lua))
            return f"RUN {script_name}"

        @staticmethod
        def rcon_exec(command):
            calls.append(("command", command))
            return "123"

    monkeypatch.setattr(module, "_load_rcon_run", lambda: FakeHelper)

    payload = _payload(module.factorio_script("read.tick"))

    assert payload == {"ok": True, "name": "read.tick", "output": "123"}
    assert calls[0][0] == "query_tick.lua"
    assert calls[1] == ("command", "RUN query_tick.lua")


def test_passes_args_to_query_type_script(monkeypatch):
    module = _load_module()
    captured = {}

    class FakeHelper:
        @staticmethod
        def build_command(script_name, lua, args):
            captured["script_name"] = script_name
            captured["args"] = args
            return "RUN"

        @staticmethod
        def rcon_exec(command):
            return "summary"

    monkeypatch.setattr(module, "_load_rcon_run", lambda: FakeHelper)

    payload = _payload(module.factorio_script("read.game_state", {"query": "resources"}))

    assert payload["output"] == "summary"
    assert captured == {"script_name": "query_game_state.lua", "args": {"query": "resources"}}


def test_wait_seconds_rejects_out_of_range_value():
    module = _load_module()

    result = module.factorio_script("wait.seconds", {"seconds": 90})
    payload = json.loads(result.output)

    assert result.success is False
    assert result.kind == "argument_error"
    assert payload["error"] == "args.seconds must be between 0 and 60"


def test_unknown_script_reports_available_names():
    module = _load_module()

    result = module.factorio_script("action.raw_lua")
    payload = json.loads(result.output)

    assert result.success is False
    assert result.kind == "argument_error"
    assert payload["error"] == "unknown script"
    assert "read.tick" in payload["available"]
