"""Factorio RCON tool — sends console commands to the sidecar server.

Connects to the Factorio headless server running in the same pod at
localhost:27015.  The RCON password is read from the environment variable
FACTORIO_RCON_PASSWORD (default: yoitsu-smoke, matching the capability).

Uses the shared RCON protocol module for packet handling.
"""
from __future__ import annotations

import socket
import struct

from tools.rcon_protocol import (
    _SERVERDATA_AUTH,
    _SERVERDATA_AUTH_RESPONSE,
    _SERVERDATA_EXECCOMMAND,
    _SERVERDATA_RESPONSE_VALUE,
    _MAX_OUTPUT,
    _RCON_HOST,
    _RCON_PASSWORD,
    _RCON_PORT,
    _pack,
    _recv_exact,
    _unpack,
)

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


def _rcon_call(host: str, port: int, password: str, command: str, timeout: float = 15.0) -> str:
    """Open a fresh RCON connection, send one command, return response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((host, port))
    try:
        # Authenticate
        sock.sendall(_pack(1, _SERVERDATA_AUTH, password))
        size_data = _recv_exact(sock, 4)
        (size,) = struct.unpack("<i", size_data)
        resp_data = _recv_exact(sock, size)
        rid, rtype, _ = _unpack(resp_data)
        # Skip optional RESPONSE_VALUE before AUTH_RESPONSE
        if rtype == _SERVERDATA_RESPONSE_VALUE:
            size_data = _recv_exact(sock, 4)
            (size,) = struct.unpack("<i", size_data)
            resp_data = _recv_exact(sock, size)
            rid, rtype, _ = _unpack(resp_data)
        if rtype != _SERVERDATA_AUTH_RESPONSE or rid == -1:
            raise RuntimeError("RCON authentication failed")

        # Send command
        sock.sendall(_pack(2, _SERVERDATA_EXECCOMMAND, command))
        size_data = _recv_exact(sock, 4)
        (size,) = struct.unpack("<i", size_data)
        resp_data = _recv_exact(sock, size)
        _, _, body = _unpack(resp_data)
        return body
    finally:
        sock.close()


def factorio_rcon(command: str) -> object:
    """Send an RCON command to the Factorio server and return the response."""
    try:
        output = _rcon_call(_RCON_HOST, _RCON_PORT, _RCON_PASSWORD, command)
    except Exception as exc:
        from runner.tools import ToolResult
        return ToolResult(success=False, output=f"RCON error: {exc}")

    if len(output.encode("utf-8")) >= _MAX_OUTPUT:
        output = "[TRUNCATED]\n" + output[:_MAX_OUTPUT - 12]

    from runner.tools import ToolResult
    return ToolResult(success=True, output=output or "(empty response)")


factorio_rcon.__is_tool__ = True  # type: ignore[attr-defined]
factorio_rcon.__tool_schema__ = {  # type: ignore[attr-defined]
    "type": "function",
    "function": {
        "name": "factorio_rcon",
        "description": (
            "Send a console command to the Factorio server via RCON and return its output. "
            "Use Lua commands prefixed with /c for scripting, e.g. "
            "/c rcon.print(game.tick) or /c game.player.print('hi'). "
            "Use /help for a list of built-in commands."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Factorio console command, e.g. '/c rcon.print(game.tick)'",
                },
            },
            "required": ["command"],
        },
    },
}
