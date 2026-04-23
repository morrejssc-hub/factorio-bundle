"""Factorio headless server capability.

setup(ctx)    → start factoriotools/factorio:stable sidecar, wait for RCON
finalize(ctx) → stop container

Events emitted (canonical):
- coordinator.capability.completed  data.name encodes sub-operation
- coordinator.capability.failed     data.name encodes sub-operation

RCON is available at localhost:27016 inside the pod.
Password: FACTORIO_RCON_PASSWORD="yoitsu-smoke"
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
import urllib.request

from coordinator.capability import CapabilityContext, CapabilityResult, EventSpec

logger = logging.getLogger(__name__)

RCON_PASSWORD = "yoitsu-smoke"
FACTORIO_PORT = 34198
RCON_PORT = 27016

_container_id: str | None = None


def _auth_headers(pod_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {pod_token}"}


def setup(ctx: CapabilityContext) -> CapabilityResult:
    global _container_id

    events: list[EventSpec] = []

    if ctx.role != "worker":
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "factorio.skipped", "job_id": ctx.job_id, "role": ctx.role},
        ))
        return CapabilityResult(ok=True, events=events)

    try:
        factorio_data_vol = os.environ.get("POD_COMMS_VOL", "")
        factorio_data_path = Path("/volumes/comms")
        (factorio_data_path / "config").mkdir(parents=True, exist_ok=True)
        (factorio_data_path / "config" / "rconpw").write_text(RCON_PASSWORD)

        payload = json.dumps({
            "name": "factorio-server",
            "image": "docker.io/factoriotools/factorio:stable",
            "env": {
                "PORT": str(FACTORIO_PORT),
                "RCON_PORT": str(RCON_PORT),
            },
            "volumes": [f"{factorio_data_vol}:/factorio:rw"] if factorio_data_vol else [],
        }).encode()
        req = urllib.request.Request(
            f"{ctx.trenni_url}/containers",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {ctx.pod_token}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        _container_id = body["container_id"]

        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "factorio.container_started", "job_id": ctx.job_id,
                  "container_id": _container_id, "factorio_port": FACTORIO_PORT,
                  "rcon_port": RCON_PORT},
        ))
        logger.info(f"[{ctx.job_id}] Factorio container started: {_container_id}")

        # Wait for container to reach running state
        for _ in range(60):
            status_req = urllib.request.Request(
                f"{ctx.trenni_url}/containers/{_container_id}",
                headers=_auth_headers(ctx.pod_token),
            )
            with urllib.request.urlopen(status_req, timeout=10) as resp:
                status = json.loads(resp.read())
            if status.get("state") == "running":
                logger.info(f"[{ctx.job_id}] Factorio container running, waiting for server init…")
                break
            time.sleep(2)
        else:
            return CapabilityResult(
                ok=False, events=events,
                error="Factorio container did not reach running state within 120s",
            )

        # Wait for map generation and RCON to open
        time.sleep(30)
        logger.info(f"[{ctx.job_id}] Factorio server ready (RCON at localhost:{RCON_PORT})")

        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "factorio.ready", "job_id": ctx.job_id,
                  "rcon_port": RCON_PORT, "rcon_password": RCON_PASSWORD},
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

    if not _container_id:
        logger.info(f"[{ctx.job_id}] No Factorio container to stop")
        return CapabilityResult(ok=True, events=events)

    try:
        req = urllib.request.Request(
            f"{ctx.trenni_url}/containers/{_container_id}",
            headers=_auth_headers(ctx.pod_token),
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"[{ctx.job_id}] Factorio container stopped: {_container_id}")

        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "factorio.container_stopped", "job_id": ctx.job_id,
                  "container_id": _container_id},
        ))
        _container_id = None
        return CapabilityResult(ok=True, events=events)

    except Exception as exc:
        logger.warning(f"[{ctx.job_id}] Could not stop Factorio container: {exc}")
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "factorio.container_stop_failed", "job_id": ctx.job_id,
                  "container_id": _container_id, "error": str(exc)},
        ))
        return CapabilityResult(ok=True, events=events)  # soft failure
