"""Shared Source RCON protocol implementation for Factorio tools.

Provides the low-level RCON packet packing/unpacking, socket helpers,
protocol constants, and default configuration used by both
factorio_rcon and factorio_rcon_batch.
"""
from __future__ import annotations

import os
import socket
import struct

# ---------------------------------------------------------------------------
# Source RCON protocol constants
# ---------------------------------------------------------------------------

_SERVERDATA_AUTH = 3
_SERVERDATA_AUTH_RESPONSE = 2
_SERVERDATA_EXECCOMMAND = 2
_SERVERDATA_RESPONSE_VALUE = 0

# ---------------------------------------------------------------------------
# Packet helpers
# ---------------------------------------------------------------------------


def _pack(request_id: int, ptype: int, body: str) -> bytes:
    """Pack a Source RCON request packet."""
    b = body.encode("utf-8")
    size = 4 + 4 + len(b) + 2
    return struct.pack(f"<iii{len(b)}scc", size, request_id, ptype, b, b"\x00", b"\x00")


def _unpack(data: bytes) -> tuple[int, int, str]:
    """Unpack a Source RCON response packet into (request_id, type, body)."""
    if len(data) < 10:
        raise RuntimeError(f"RCON packet too short: {len(data)}")
    rid, ptype = struct.unpack_from("<ii", data, 0)
    body = data[8:-2].decode("utf-8", errors="replace") if len(data) > 10 else ""
    return rid, ptype, body


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly *n* bytes from *sock*, raising on early close."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError(f"RCON connection closed after {len(buf)}/{n} bytes")
        buf.extend(chunk)
    return bytes(buf)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

_RCON_HOST = "localhost"
_RCON_PORT = int(os.environ.get("FACTORIO_RCON_PORT", "27016"))
_RCON_PASSWORD = os.environ.get("FACTORIO_RCON_PASSWORD", "yoitsu-smoke")
_MAX_OUTPUT = 4096
