"""Structured Factorio script tool.

This is the worker-facing tool for Factorio automation. It keeps the model on
named bundle primitives instead of exposing raw RCON or arbitrary shell.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import time
from typing import Any


_BUNDLE_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _BUNDLE_ROOT / "scripts"
_RCON_RUN_PATH = _SCRIPTS_DIR / "rcon_run.py"

_SCRIPT_MAP = {
    "read.tick": "query_tick.lua",
    "read.world_summary": "query_all.lua",
    "read.game_state": "query_game_state.lua",
    "read.production": "query_production.lua",
    "read.logistics": "query_logistics.lua",
    "read.research": "query_research.lua",
    "read.iron_plate_line": "query_iron_plate_line.lua",
    "action.build_iron_plate_line": "build_iron_plate_line.lua",
}


def _tool_result(success: bool, output: object, kind: str = "ok") -> object:
    from runner.tools import ToolResult

    if not isinstance(output, str):
        output = json.dumps(output, ensure_ascii=False, sort_keys=True)
    return ToolResult(success=success, output=output, kind=kind)  # type: ignore[arg-type]


def _load_rcon_run() -> object:
    spec = importlib.util.spec_from_file_location("_factorio_bundle_rcon_run", _RCON_RUN_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load rcon helper: {_RCON_RUN_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _normalize_args(args: dict[str, Any] | None) -> dict[str, object]:
    if args is None:
        return {}
    if not isinstance(args, dict):
        raise TypeError("args must be an object")
    return dict(args)


def _run_lua_script(name: str, args: dict[str, object]) -> object:
    script_name = _SCRIPT_MAP[name]
    script_path = _SCRIPTS_DIR / script_name
    if not script_path.exists():
        return _tool_result(
            False,
            {"ok": False, "name": name, "error": f"script not found: {script_name}"},
            "runtime_error",
        )

    helper = _load_rcon_run()
    lua = script_path.read_text(encoding="utf-8")
    command = helper.build_command(script_name, lua, args)
    output = helper.rcon_exec(command)
    return _tool_result(True, {"ok": True, "name": name, "output": output or "(empty response)"})


def factorio_script(name: str, args: dict[str, Any] | None = None) -> object:
    """Run a named Factorio bundle primitive.

    The supported names are intentionally small and explicit. Use
    `system.capabilities` to list them at runtime.
    """
    try:
        params = _normalize_args(args)
    except TypeError as exc:
        return _tool_result(False, {"ok": False, "name": name, "error": str(exc)}, "argument_error")

    if name == "system.capabilities":
        return _tool_result(
            True,
            {
                "ok": True,
                "names": sorted([*list(_SCRIPT_MAP), "system.capabilities", "wait.seconds"]),
            },
        )

    if name == "wait.seconds":
        seconds = params.get("seconds", 1)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            return _tool_result(
                False,
                {"ok": False, "name": name, "error": "args.seconds must be a number"},
                "argument_error",
            )
        if seconds < 0 or seconds > 60:
            return _tool_result(
                False,
                {"ok": False, "name": name, "error": "args.seconds must be between 0 and 60"},
                "argument_error",
            )
        time.sleep(float(seconds))
        return _tool_result(True, {"ok": True, "name": name, "waited_seconds": seconds})

    if name not in _SCRIPT_MAP:
        return _tool_result(
            False,
            {
                "ok": False,
                "name": name,
                "error": "unknown script",
                "available": sorted([*list(_SCRIPT_MAP), "system.capabilities", "wait.seconds"]),
            },
            "argument_error",
        )

    try:
        return _run_lua_script(name, params)
    except Exception as exc:
        return _tool_result(False, {"ok": False, "name": name, "error": str(exc)}, "runtime_error")


factorio_script.__is_tool__ = True  # type: ignore[attr-defined]
factorio_script.__tool_schema__ = {  # type: ignore[attr-defined]
    "type": "function",
    "function": {
        "name": "factorio_script",
        "description": (
            "Run a named Factorio bundle primitive. Use this instead of raw RCON, "
            "shell commands, or Lua snippets. Supported names include "
            "read.tick, read.world_summary, read.game_state, read.production, "
            "read.logistics, read.research, read.iron_plate_line, "
            "action.build_iron_plate_line, wait.seconds, and system.capabilities."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Primitive name, e.g. read.tick or action.build_iron_plate_line",
                },
                "args": {
                    "type": "object",
                    "description": "Optional primitive arguments, e.g. {'query': 'summary'} or {'seconds': 5}",
                },
            },
            "required": ["name"],
        },
    },
}
