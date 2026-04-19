"""Factorio RCON batch tool — executes multiple RCON commands over a single connection.

Connects to the Factorio headless server running in the same pod at
localhost:27015.  The RCON password is read from the environment variable
FACTORIO_RCON_PASSWORD (default: yoitsu-smoke, matching the capability).

Unlike the single-command factorio_rcon tool, this tool opens one TCP
connection, authenticates once, sends every command in the list, collects
all responses, and then closes the connection.  This avoids the per-command
TCP connect/auth/close overhead when a worker needs to issue several queries
(e.g. tick, entities, resources) in sequence.

Includes a self-contained Source RCON protocol client so the module has
no runtime dependencies beyond the stdlib.
"""
from __future__ import annotations

import os
import socket
import struct

# ---------------------------------------------------------------------------
# Inline Source RCON client (Factorio uses this protocol)
# ---------------------------------------------------------------------------

_SERVERDATA_AUTH = 3
_SERVERDATA_AUTH_RESPONSE = 2
_SERVERDATA_EXECCOMMAND = 2
_SERVERDATA_RESPONSE_VALUE = 0


def _pack(request_id: int, ptype: int, body: str) -> bytes:
    b = body.encode("utf-8")
    size = 4 + 4 + len(b) + 2
    return struct.pack(f"<iii{len(b)}scc", size, request_id, ptype, b, b"\x00", b"\x00")


def _unpack(data: bytes) -> tuple[int, int, str]:
    if len(data) < 10:
        raise RuntimeError(f"RCON packet too short: {len(data)}")
    rid, ptype = struct.unpack_from("<ii", data, 0)
    body = data[8:-2].decode("utf-8", errors="replace") if len(data) > 10 else ""
    return rid, ptype, body


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError(f"RCON connection closed after {len(buf)}/{n} bytes")
        buf.extend(chunk)
    return bytes(buf)


def _recv_response(sock: socket.socket) -> str:
    """Read one RCON response packet from the socket and return its body."""
    size_data = _recv_exact(sock, 4)
    (size,) = struct.unpack("<i", size_data)
    resp_data = _recv_exact(sock, size)
    _, _, body = _unpack(resp_data)
    return body


def _rcon_batch_call(
    host: str,
    port: int,
    password: str,
    commands: list[str],
    timeout: float = 15.0,
) -> list[str]:
    """Open one RCON connection, authenticate once, run all commands, return responses."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((host, port))
    try:
        # Authenticate
        sock.sendall(_pack(1, _SERVERDATA_AUTH, password))

        # Read auth response(s) — Factorio may send RESPONSE_VALUE then AUTH_RESPONSE
        auth_ok = False
        while not auth_ok:
            size_data = _recv_exact(sock, 4)
            (size,) = struct.unpack("<i", size_data)
            resp_data = _recv_exact(sock, size)
            rid, rtype, _ = _unpack(resp_data)
            if rtype == _SERVERDATA_AUTH_RESPONSE:
                if rid == -1:
                    raise RuntimeError("RCON authentication failed")
                auth_ok = True
            # else: it was a RESPONSE_VALUE, keep reading

        # Execute each command
        results: list[str] = []
        for idx, command in enumerate(commands):
            sock.sendall(_pack(100 + idx, _SERVERDATA_EXECCOMMAND, command))
            body = _recv_response(sock)
            results.append(body)

        return results
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

_RCON_HOST = "localhost"
_RCON_PORT = int(os.environ.get("FACTORIO_RCON_PORT", "27015"))
_RCON_PASSWORD = os.environ.get("FACTORIO_RCON_PASSWORD", "yoitsu-smoke")
_MAX_OUTPUT = 4096


def factorio_rcon_batch(commands: list[str]) -> object:
    """Send multiple RCON commands to the Factorio server over a single connection.

    Args:
        commands: A list of Factorio console commands to execute in order.

    Returns:
        A list of response strings, one per command, in the same order.
    """
    if not commands:
        from runner.tools import ToolResult
        return ToolResult(success=False, output="No commands provided")

    try:
        outputs = _rcon_batch_call(_RCON_HOST, _RCON_PORT, _RCON_PASSWORD, commands)
    except Exception as exc:
        from runner.tools import ToolResult
        return ToolResult(success=False, output=f"RCON batch error: {exc}")

    # Truncate any individual response that is too large
    trimmed: list[str] = []
    for output in outputs:
        if len(output.encode("utf-8")) >= _MAX_OUTPUT:
            output = "[TRUNCATED]\n" + output[: _MAX_OUTPUT - 12]
        trimmed.append(output or "(empty response)")

    from runner.tools import ToolResult
    return ToolResult(success=True, output=trimmed)


factorio_rcon_batch.__is_tool__ = True  # type: ignore[attr-defined]
factorio_rcon_batch.__tool_schema__ = {  # type: ignore[attr-defined]
    "type": "function",
    "function": {
        "name": "factorio_rcon_batch",
        "description": (
            "Send multiple console commands to the Factorio server via RCON over a single "
            "TCP connection and return a list of responses. This is more efficient than "
            "calling factorio_rcon multiple times because it avoids per-command connection "
            "overhead. Use Lua commands prefixed with /c for scripting, e.g. "
            "/c rcon.print(game.tick). Provide commands as a list of strings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of Factorio console commands to execute in order, "
                        "e.g. ['/c rcon.print(game.tick)', '/c rcon.print(#game.surfaces[1].find_entities_filtered{name=\"iron-ore\"})']"
                    ),
                },
            },
            "required": ["commands"],
        },
    },
}
