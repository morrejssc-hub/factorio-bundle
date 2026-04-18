"""Factorio headless server capability.

Starts a factoriotools/factorio:stable sidecar container with RCON enabled:
  setup(ctx)    → POST /containers, poll until running, wait for init
  finalize(ctx) → DELETE /containers/{container_id}

New contract (Phase 1+):
  - setup(ctx: CapabilityContext) -> CapabilityResult
  - finalize(ctx: CapabilityContext) -> CapabilityResult
  - Returns events for coordinator to emit
  - Failure signaled via result.ok=False

RCON is available at localhost:27015 inside the pod.
Password is fixed at FACTORIO_RCON_PASSWORD="yoitsu-smoke".
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass

from coordinator.capability import CapabilityContext, CapabilityResult, EventSpec

logger = logging.getLogger(__name__)

RCON_PASSWORD = "yoitsu-smoke"
RCON_PORT = 27015

# Module-level state for container tracking
_container_id: str | None = None


def _auth_headers(pod_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {pod_token}"}


def setup(ctx: CapabilityContext) -> CapabilityResult:
    """Start Factorio server container.

    Returns CapabilityResult with events for coordinator to emit.
    """
    global _container_id

    events: list[EventSpec] = []

    try:
        payload = json.dumps({
            "name": "factorio-server",
            "image": "docker.io/factoriotools/factorio:stable",
            "env": {
                "FACTORIO_RCON_PASSWORD": RCON_PASSWORD,
                "FACTORIO_RCON_PORT": str(RCON_PORT),
            },
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
            type="capability.factorio.container_started",
            data={
                "job_id": ctx.job_id,
                "container_id": _container_id,
                "rcon_port": RCON_PORT,
            },
        ))
        logger.info(f"[{ctx.job_id}] Factorio container started: {_container_id}")

        # Wait for container process to start
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
                ok=False,
                events=events,
                error="Factorio container did not reach running state within 120s",
            )

        # Factorio needs time to generate the map and open RCON
        time.sleep(30)
        logger.info(f"[{ctx.job_id}] Factorio server ready (RCON at localhost:{RCON_PORT})")

        events.append(EventSpec(
            type="capability.factorio.ready",
            data={
                "job_id": ctx.job_id,
                "rcon_port": RCON_PORT,
                "rcon_password": RCON_PASSWORD,
            },
        ))

        return CapabilityResult(ok=True, events=events)

    except Exception as exc:
        logger.error(f"[{ctx.job_id}] Factorio setup failed: {exc}")
        return CapabilityResult(
            ok=False,
            events=events,
            error=str(exc),
        )


def finalize(ctx: CapabilityContext) -> CapabilityResult:
    """Stop Factorio server container.

    Returns CapabilityResult with events for coordinator to emit.
    """
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
            type="capability.factorio.container_stopped",
            data={
                "job_id": ctx.job_id,
                "container_id": _container_id,
            },
        ))
        _container_id = None
        return CapabilityResult(ok=True, events=events)

    except Exception as exc:
        logger.warning(f"[{ctx.job_id}] Could not stop Factorio container: {exc}")
        # Non-critical failure - container might already be stopped
        events.append(EventSpec(
            type="capability.factorio.container_stop_failed",
            data={
                "job_id": ctx.job_id,
                "container_id": _container_id,
                "error": str(exc),
            },
        ))
        return CapabilityResult(ok=True, events=events)  # Soft failure


# Legacy contract support (deprecated, will be removed in future)
def setup_legacy(*, job_id: str, trenni_url: str, pod_token: str) -> None:
    """Legacy setup function for backward compatibility."""
    ctx = CapabilityContext(
        job_id=job_id,
        trenni_url=trenni_url,
        pod_token=pod_token,
        bundle_path=None,
        target_path=None,
        role="",
    )
    result = setup(ctx)
    if not result.ok:
        raise RuntimeError(result.error)


def finalize_legacy(*, job_id: str) -> None:
    """Legacy finalize function for backward compatibility."""
    ctx = CapabilityContext(
        job_id=job_id,
        trenni_url="",
        pod_token="",
        bundle_path=None,
        target_path=None,
        role="",
    )
    result = finalize(ctx)
    if not result.ok:
        raise RuntimeError(result.error)