"""Factorio headless server capability.

setup(ctx)    starts factoriotools/factorio:stable, optionally from task_env_ref.save_ref
finalize(ctx) saves the final game state, writes an artifacts.yaml entry, and stops it

Only canonical capability events are emitted. Sub-semantics are encoded in
data.name and data.details.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import struct
import time
import urllib.request

from coordinator.capability import CapabilityContext, CapabilityResult, EventSpec
from coordinator.s3_ops import build_s3_client_from_env
from yoitsu_contracts.artifacts import (
    ArtifactEntry,
    load_artifacts_yaml,
    save_artifacts_yaml,
)

logger = logging.getLogger(__name__)

RCON_PASSWORD = "yoitsu-smoke"
FACTORIO_PORT = 34198
RCON_PORT = 27016

FACTORIO_DATA_PATH = Path("/volumes/comms")
FACTORIO_SAVES_PATH = FACTORIO_DATA_PATH / "saves"
ARTIFACTS_PATH = Path("/volumes/artifacts")

_SERVERDATA_AUTH = 3
_SERVERDATA_AUTH_RESPONSE = 2
_SERVERDATA_EXECCOMMAND = 2
_SERVERDATA_RESPONSE_VALUE = 0

_container_id: str | None = None


def _auth_headers(pod_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {pod_token}"}


def setup(ctx: CapabilityContext) -> CapabilityResult:
    global _container_id

    events: list[EventSpec] = []

    try:
        factorio_data_vol = os.environ.get("POD_COMMS_VOL", "")
        FACTORIO_SAVES_PATH.mkdir(parents=True, exist_ok=True)
        (FACTORIO_DATA_PATH / "config").mkdir(parents=True, exist_ok=True)
        (FACTORIO_DATA_PATH / "config" / "rconpw").write_text(RCON_PASSWORD)
        _write_server_settings()

        staged_save = _stage_initial_save(ctx)
        env = {
            "PORT": str(FACTORIO_PORT),
            "RCON_PORT": str(RCON_PORT),
            "FACTORIO_RCON_PASSWORD": RCON_PASSWORD,
        }
        if staged_save is not None:
            env["SAVE_NAME"] = staged_save.stem
            env["LOAD_LATEST_SAVE"] = "true"
            env["GENERATE_NEW_SAVE"] = "false"

        payload = json.dumps({
            "name": "factorio-server",
            "image": "docker.io/factoriotools/factorio:stable",
            "env": env,
            "volumes": [f"{factorio_data_vol}:/factorio:rw"] if factorio_data_vol else [],
        }).encode()
        req = urllib.request.Request(
            f"{ctx.trenni_url}/containers",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ctx.pod_token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        _container_id = body["container_id"]

        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={
                "name": "factorio.container_started",
                "job_id": ctx.job_id,
                "role": ctx.role,
                "container_id": _container_id,
                "factorio_port": FACTORIO_PORT,
                "rcon_port": RCON_PORT,
                "details": {
                    "initial_save": str(staged_save) if staged_save is not None else "",
                },
            },
        ))
        logger.info(f"[{ctx.job_id}] Factorio container started: {_container_id}")

        _wait_container_running(ctx, _container_id)
        _wait_rcon_ready()

        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={
                "name": "factorio.ready",
                "job_id": ctx.job_id,
                "role": ctx.role,
                "rcon_port": RCON_PORT,
                "rcon_password": RCON_PASSWORD,
            },
        ))
        return CapabilityResult(ok=True, events=events)

    except Exception as exc:
        logger.error(f"[{ctx.job_id}] Factorio setup failed: {exc}")
        events.append(EventSpec(
            type="coordinator.capability.failed",
            data={"name": "factorio.setup_failed", "job_id": ctx.job_id, "error": str(exc)},
        ))
        return CapabilityResult(ok=False, events=events, error=str(exc))


def finalize(ctx: CapabilityContext) -> CapabilityResult:
    global _container_id

    events: list[EventSpec] = []
    ok = True
    error: str | None = None

    if not _container_id:
        logger.info(f"[{ctx.job_id}] No Factorio container to stop")
        return CapabilityResult(ok=True, events=events)

    try:
        if ctx.role == "worker":
            final_ref = _write_final_save_ref(ctx)
            if final_ref is not None:
                events.append(EventSpec(
                    type="coordinator.capability.completed",
                    data={
                        "name": "factorio.final_save_ref",
                        "phase": "finalize",
                        "job_id": ctx.job_id,
                        "task_id": ctx.task_id,
                        "role": ctx.role,
                        "details": {"final_save_ref": final_ref},
                    },
                ))
        elif ctx.role == "auditor":
            audit_result = _run_audit_case(ctx)
            events.append(EventSpec(
                type="coordinator.capability.completed",
                data={
                    "name": "factorio.audit_result",
                    "phase": "finalize",
                    "job_id": ctx.job_id,
                    "task_id": ctx.task_id,
                    "role": ctx.role,
                    "details": audit_result,
                },
            ))

    except Exception as exc:
        ok = False
        error = str(exc)
        logger.error(f"[{ctx.job_id}] Factorio finalize failed: {exc}")
        events.append(EventSpec(
            type="coordinator.capability.failed",
            data={"name": "factorio.finalize_failed", "job_id": ctx.job_id, "error": str(exc)},
        ))

    finally:
        if _container_id:
            stop_event = _stop_container(ctx)
            events.append(stop_event)
            _container_id = None

    return CapabilityResult(ok=ok, events=events, error=error)


def _stage_initial_save(ctx: CapabilityContext) -> Path | None:
    save_ref = (ctx.task_env_ref or {}).get("save_ref")
    if not isinstance(save_ref, dict) or not save_ref.get("uri"):
        return None

    uri = str(save_ref["uri"])
    dest = FACTORIO_SAVES_PATH / _safe_save_name(uri)
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = str(save_ref.get("digest") or "")
    expected_size = int(save_ref.get("size") or 0)

    if uri.startswith("s3://"):
        s3 = build_s3_client_from_env()
        if s3 is None:
            raise RuntimeError("S3_ENDPOINT is required to download task_env_ref.save_ref")
        s3.download(uri, dest, expected_hash=digest)
    elif uri.startswith("file://"):
        src = Path(uri[7:])
        if not src.exists():
            raise FileNotFoundError(f"save_ref file not found: {src}")
        shutil.copy2(src, dest)
    else:
        raise ValueError(f"Unsupported save_ref uri: {uri}")

    actual_size = dest.stat().st_size
    if expected_size and actual_size != expected_size:
        raise ValueError(
            f"save_ref size mismatch: expected {expected_size}, got {actual_size}"
        )
    if digest:
        actual = f"sha256:{_sha256(dest)}"
        if actual != digest:
            raise ValueError(f"save_ref digest mismatch: expected {digest}, got {actual}")
    return dest


def _write_server_settings() -> None:
    settings = {
        "name": "yoitsu-local-factorio",
        "description": "Local Yoitsu Factorio capability server",
        "tags": [],
        "max_players": 0,
        "visibility": {"public": False, "lan": False},
        "username": "",
        "password": "",
        "token": "",
        "game_password": "",
        "require_user_verification": False,
        "max_upload_in_kilobytes_per_second": 0,
        "max_upload_slots": 5,
        "minimum_latency_in_ticks": 0,
        "max_heartbeats_per_second": 60,
        "ignore_player_limit_for_returning_players": False,
        "allow_commands": "admins-only",
        "autosave_interval": 10,
        "autosave_slots": 5,
        "afk_autokick_interval": 0,
        "auto_pause": True,
        "auto_pause_when_players_connect": False,
        "only_admins_can_pause_the_game": True,
        "autosave_only_on_server": True,
        "non_blocking_saving": False,
        "minimum_segment_size": 25,
        "minimum_segment_size_peer_count": 20,
        "maximum_segment_size": 100,
        "maximum_segment_size_peer_count": 10,
    }
    path = FACTORIO_DATA_PATH / "config" / "server-settings.json"
    path.write_text(json.dumps(settings, indent=2) + "\n")


def _write_final_save_ref(ctx: CapabilityContext) -> dict[str, object] | None:
    if not os.environ.get("S3_ENDPOINT"):
        logger.warning(
            f"[{ctx.job_id}] S3_ENDPOINT not configured; final_save_ref will not be emitted. "
            "Set S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, and S3_REGION."
        )
        return None

    before = _latest_save_mtime()
    _rcon_call("/server-save", timeout=30.0)
    final_save = _wait_for_latest_save(after_mtime=before)
    digest = f"sha256:{_sha256(final_save)}"
    size = final_save.stat().st_size

    artifact_name = f"factorio-final-save-{ctx.job_id}.zip"
    artifact_path = ARTIFACTS_PATH / artifact_name
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final_save, artifact_path)

    bucket = os.environ.get("S3_BUCKET", "yoitsu-artifacts")
    key = f"factorio/final-saves/{ctx.task_id or ctx.job_id}/{ctx.job_id}.zip"
    uri = f"s3://{bucket}/{key}"
    _record_artifact(ctx.bundle_path / "artifacts.yaml", artifact_name, uri, digest, size, ctx.job_id)
    return {"uri": uri, "digest": digest, "size": size}


def _run_audit_case(ctx: CapabilityContext) -> dict[str, object]:
    task_env = ctx.task_env_ref or {}
    case_id = str(task_env.get("case_id") or "bootstrap-base")
    suite = _load_suite(ctx.bundle_path)
    case = _find_case(suite, case_id)
    acceptance_path = ctx.bundle_path / case["acceptance"]["path"]
    if not acceptance_path.exists():
        raise FileNotFoundError(f"acceptance script not found: {acceptance_path}")

    command = _lua_console_command(acceptance_path.read_text())
    output = _rcon_call(command, timeout=60.0)
    metrics = _parse_metrics(output)
    passed, failures = _evaluate_pass_criteria(metrics, case.get("pass_criteria") or {})
    result = {
        "case_id": case_id,
        "suite_version": suite.get("version", 0),
        "metrics": metrics,
        "pass": passed,
        "failures": failures,
    }

    if os.environ.get("S3_ENDPOINT"):
        payload = json.dumps(result, sort_keys=True, indent=2).encode()
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        artifact_name = f"factorio-audit-{case_id}-{ctx.job_id}.json"
        artifact_path = ARTIFACTS_PATH / artifact_name
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(payload)
        bucket = os.environ.get("S3_BUCKET", "yoitsu-artifacts")
        uri = f"s3://{bucket}/factorio/audit/{case_id}/{ctx.job_id}.json"
        _record_artifact(
            ctx.bundle_path / "artifacts.yaml",
            artifact_name,
            uri,
            digest,
            len(payload),
            ctx.job_id,
        )
        result["artifact_ref"] = {"uri": uri, "digest": digest, "size": len(payload)}

    return result


def _lua_console_command(script: str) -> str:
    """Factorio console commands are single-line; load the original Lua chunk."""
    encoded = json.dumps(script)
    return f"/c assert(load({encoded}))()"


def _load_suite(bundle_path: Path) -> dict:
    import yaml
    suite_path = bundle_path / "audit" / "suite.yaml"
    with open(suite_path) as f:
        suite = yaml.safe_load(f) or {}
    if not isinstance(suite, dict):
        raise ValueError("audit suite.yaml must be a mapping")
    return suite


def _find_case(suite: dict, case_id: str) -> dict:
    for case in suite.get("cases") or []:
        if isinstance(case, dict) and case.get("id") == case_id:
            return case
    raise ValueError(f"audit case not found: {case_id}")


def _parse_metrics(output: str) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"acceptance script did not print JSON metrics: {output[:200]}")


def _evaluate_pass_criteria(metrics: dict[str, object], criteria: dict) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for key, expected in criteria.items():
        if key.endswith("_min"):
            metric_key = key[:-4]
            actual = metrics.get(metric_key)
            if not isinstance(actual, (int, float)) or actual < expected:
                failures.append(f"{metric_key}={actual!r} below minimum {expected!r}")
        elif key == "must_complete":
            actual = bool(metrics.get("must_complete"))
            if bool(expected) and not actual:
                failures.append("must_complete is false")
        else:
            if metrics.get(key) != expected:
                failures.append(f"{key}={metrics.get(key)!r} expected {expected!r}")
    return not failures, failures


def _record_artifact(
    manifest_path: Path,
    name: str,
    uri: str,
    digest: str,
    size: int,
    job_id: str,
) -> None:
    import datetime as _dt
    manifest = load_artifacts_yaml(manifest_path)
    manifest.artifacts[name] = ArtifactEntry(
        s3_uri=uri,
        content_hash=digest,
        updated_by=job_id,
        updated_at=_dt.datetime.now(_dt.UTC).isoformat(),
        size_bytes=size,
    )
    save_artifacts_yaml(manifest_path, manifest)


def _wait_container_running(ctx: CapabilityContext, container_id: str) -> None:
    for _ in range(60):
        status_req = urllib.request.Request(
            f"{ctx.trenni_url}/containers/{container_id}",
            headers=_auth_headers(ctx.pod_token),
        )
        with urllib.request.urlopen(status_req, timeout=10) as resp:
            status = json.loads(resp.read())
        if status.get("state") == "running":
            logger.info(f"[{ctx.job_id}] Factorio container running")
            return
        time.sleep(2)
    raise TimeoutError("Factorio container did not reach running state within 120s")


def _wait_rcon_ready() -> None:
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            _rcon_call("/silent-command rcon.print(game.tick)", timeout=5.0)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise TimeoutError(f"Factorio RCON did not become ready: {last_error}")


def _stop_container(ctx: CapabilityContext) -> EventSpec:
    assert _container_id is not None
    try:
        req = urllib.request.Request(
            f"{ctx.trenni_url}/containers/{_container_id}",
            headers=_auth_headers(ctx.pod_token),
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"[{ctx.job_id}] Factorio container stopped: {_container_id}")
        return EventSpec(
            type="coordinator.capability.completed",
            data={
                "name": "factorio.container_stopped",
                "job_id": ctx.job_id,
                "container_id": _container_id,
            },
        )
    except Exception as exc:
        logger.warning(f"[{ctx.job_id}] Could not stop Factorio container: {exc}")
        return EventSpec(
            type="coordinator.capability.completed",
            data={
                "name": "factorio.container_stop_failed",
                "job_id": ctx.job_id,
                "container_id": _container_id,
                "error": str(exc),
            },
        )


def _latest_save_mtime() -> float:
    saves = list(FACTORIO_SAVES_PATH.glob("*.zip"))
    if not saves:
        return 0.0
    return max(path.stat().st_mtime for path in saves)


def _wait_for_latest_save(*, after_mtime: float, timeout: float = 30.0) -> Path:
    deadline = time.monotonic() + timeout
    latest: Path | None = None
    while time.monotonic() < deadline:
        saves = sorted(FACTORIO_SAVES_PATH.glob("*.zip"), key=lambda p: p.stat().st_mtime)
        if saves:
            latest = saves[-1]
            if latest.stat().st_mtime > after_mtime:
                return latest
        time.sleep(1)
    if latest is None:
        raise FileNotFoundError(f"No Factorio save found in {FACTORIO_SAVES_PATH}")
    raise TimeoutError(
        f"No Factorio save newer than mtime {after_mtime} found in {FACTORIO_SAVES_PATH}"
    )


def _safe_save_name(uri: str) -> str:
    name = uri.rsplit("/", 1)[-1] or "input.zip"
    if not name.endswith(".zip"):
        name = f"{name}.zip"
    return "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", ".")) or "input.zip"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pack(request_id: int, ptype: int, body: str) -> bytes:
    encoded = body.encode("utf-8")
    size = 4 + 4 + len(encoded) + 2
    return struct.pack(f"<iii{len(encoded)}scc", size, request_id, ptype, encoded, b"\x00", b"\x00")


def _unpack(data: bytes) -> tuple[int, int, str]:
    request_id, ptype = struct.unpack_from("<ii", data, 0)
    body = data[8:-2].decode("utf-8", errors="replace") if len(data) > 10 else ""
    return request_id, ptype, body


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError(f"RCON connection closed after {len(buf)}/{n} bytes")
        buf.extend(chunk)
    return bytes(buf)


def _rcon_call(command: str, timeout: float = 15.0) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(("localhost", RCON_PORT))
    try:
        sock.sendall(_pack(1, _SERVERDATA_AUTH, RCON_PASSWORD))
        size_data = _recv_exact(sock, 4)
        (size,) = struct.unpack("<i", size_data)
        resp_data = _recv_exact(sock, size)
        rid, rtype, _ = _unpack(resp_data)
        if rtype == _SERVERDATA_RESPONSE_VALUE:
            size_data = _recv_exact(sock, 4)
            (size,) = struct.unpack("<i", size_data)
            resp_data = _recv_exact(sock, size)
            rid, rtype, _ = _unpack(resp_data)
        if rtype != _SERVERDATA_AUTH_RESPONSE or rid == -1:
            raise RuntimeError("RCON authentication failed")

        sock.sendall(_pack(2, _SERVERDATA_EXECCOMMAND, command))
        size_data = _recv_exact(sock, 4)
        (size,) = struct.unpack("<i", size_data)
        resp_data = _recv_exact(sock, size)
        _, _, body = _unpack(resp_data)
        return body
    finally:
        sock.close()
