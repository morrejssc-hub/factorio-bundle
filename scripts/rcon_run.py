"""Run a Lua script file via Factorio RCON.

Usage:
    python3 /volumes/bundle/scripts/rcon_run.py <script.lua> [arg1=v1 ...]

The script is JSON-encoded and sent as a single-line /silent-command
assert(load(...))() command, which works for multi-line Lua without the
"Unknown command" error that occurs when a Lua command is followed by a
newline in the RCON stream.

Optional key=value pairs after the script path are passed to script query()
functions as a params table, e.g.:
    rcon_run.py query_all.lua force=player limit=20
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import struct
import sys


_HOST = "localhost"
_PORT = int(os.environ.get("FACTORIO_RCON_PORT", "27016"))
_PASSWORD = os.environ.get("FACTORIO_RCON_PASSWORD", "yoitsu-smoke")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUERY_TYPE_SCRIPTS = {
    "query_game_state.lua",
    "query_logistics.lua",
    "query_production.lua",
}


def _lua_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _pack(rid: int, ptype: int, body: str) -> bytes:
    b = body.encode("utf-8")
    size = 4 + 4 + len(b) + 2
    return struct.pack(f"<iii{len(b)}scc", size, rid, ptype, b, b"\x00", b"\x00")


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError(f"connection closed after {len(buf)}/{n} bytes")
        buf.extend(chunk)
    return bytes(buf)


def _unpack(data: bytes) -> tuple[int, int, str]:
    rid, ptype = struct.unpack_from("<ii", data, 0)
    body = data[8:-2].decode("utf-8", errors="replace") if len(data) > 10 else ""
    return rid, ptype, body


def rcon_exec(command: str, timeout: float = 30.0) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((_HOST, _PORT))
    try:
        sock.sendall(_pack(1, 3, _PASSWORD))
        size, = struct.unpack("<i", _recv_exact(sock, 4))
        rid, rtype, _ = _unpack(_recv_exact(sock, size))
        if rtype == 0:
            size, = struct.unpack("<i", _recv_exact(sock, 4))
            rid, rtype, _ = _unpack(_recv_exact(sock, size))
        if rtype != 2 or rid == -1:
            raise RuntimeError("RCON auth failed")
        sock.sendall(_pack(2, 2, command))
        size, = struct.unpack("<i", _recv_exact(sock, 4))
        _, _, body = _unpack(_recv_exact(sock, size))
        return body
    finally:
        sock.close()


def _parse_value(value: str) -> object:
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _lua_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return _lua_string(str(value))


def _parse_params(args: list[str]) -> dict[str, object]:
    params: dict[str, object] = {}
    for arg in args:
        if "=" not in arg:
            raise ValueError(f"expected key=value argument, got: {arg}")
        key, value = arg.split("=", 1)
        if not _IDENT_RE.match(key):
            raise ValueError(f"invalid Lua identifier for argument key: {key}")
        params[key] = _parse_value(value)
    return params


def _params_literal(params: dict[str, object]) -> str:
    parts = [f"{key} = {_lua_literal(value)}" for key, value in params.items()]
    return "{ " + ", ".join(parts) + " }"


def build_command(script_name: str, lua: str, params: dict[str, object]) -> str:
    """Build a single-line Factorio /c command for an existing bundle script."""
    params_lua = _params_literal(params)
    if Path(script_name).name in _QUERY_TYPE_SCRIPTS:
        query_type = str(params.get("query") or params.get("query_type") or "summary")
        call = f"__result.query({_lua_string(query_type)}, __params)"
    else:
        call = "__result.query(__params)"

    wrapper = f"""
local __chunk = assert(load({_lua_string(lua)}))
local __result = __chunk()
local __params = {params_lua}
if type(__result) == "table" and type(__result.query) == "function" then
  local __value = {call}
  if __value ~= nil and type(__value) ~= "table" then
    rcon.print(tostring(__value))
  end
elseif __result ~= nil then
  rcon.print(tostring(__result))
end
"""
    return f"/silent-command assert(load({_lua_string(wrapper)}))()"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: rcon_run.py <script.lua> [key=value ...]", file=sys.stderr)
        sys.exit(1)

    script_path = sys.argv[1]
    if not os.path.isabs(script_path):
        script_path = os.path.join(os.path.dirname(__file__), script_path)

    with open(script_path, encoding="utf-8") as f:
        lua = f.read()

    try:
        params = _parse_params(sys.argv[2:])
    except ValueError as exc:
        print(f"rcon_run.py: {exc}", file=sys.stderr)
        sys.exit(2)

    command = build_command(os.path.basename(script_path), lua, params)
    output = rcon_exec(command)
    print(output or "(empty response)")


if __name__ == "__main__":
    main()
