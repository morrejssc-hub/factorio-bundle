"""Factorio headless server capability.

Starts a factoriotools/factorio:stable sidecar container with RCON enabled:
  setup()    → POST /pods/{pod_id}/containers, poll until running, wait for init
  finalize() → DELETE /pods/{pod_id}/containers/{container_id}

RCON is available at localhost:27015 inside the pod.
Password is fixed at FACTORIO_RCON_PASSWORD="yoitsu-smoke".
"""
import json
import logging
import time
import urllib.request

logger = logging.getLogger(__name__)

RCON_PASSWORD = "yoitsu-smoke"
RCON_PORT = 27015

_container_id: str | None = None
_trenni_url: str | None = None
_pod_id: str | None = None


def setup(*, job_id: str, trenni_url: str, pod_id: str) -> None:
    global _container_id, _trenni_url, _pod_id
    _trenni_url = trenni_url
    _pod_id = pod_id

    payload = json.dumps({
        "name": "factorio-server",
        "image": "docker.io/factoriotools/factorio:stable",
        "env": {
            "FACTORIO_RCON_PASSWORD": RCON_PASSWORD,
            "FACTORIO_RCON_PORT": str(RCON_PORT),
        },
    }).encode()
    req = urllib.request.Request(
        f"{trenni_url}/pods/{pod_id}/containers",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    _container_id = body["container_id"]
    logger.info(f"[{job_id}] Factorio container started: {_container_id}")

    # Wait for container process to start
    for _ in range(60):
        status_req = urllib.request.Request(
            f"{trenni_url}/pods/{pod_id}/containers/{_container_id}"
        )
        with urllib.request.urlopen(status_req, timeout=10) as resp:
            status = json.loads(resp.read())
        if status.get("state") == "running":
            logger.info(f"[{job_id}] Factorio container running, waiting for server init…")
            break
        time.sleep(2)
    else:
        raise RuntimeError("Factorio container did not reach running state within 120s")

    # Factorio needs time to generate the map and open RCON
    time.sleep(30)
    logger.info(f"[{job_id}] Factorio server ready (RCON at localhost:{RCON_PORT})")


def finalize(*, job_id: str) -> None:
    if not (_container_id and _trenni_url and _pod_id):
        return
    req = urllib.request.Request(
        f"{_trenni_url}/pods/{_pod_id}/containers/{_container_id}",
        method="DELETE",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"[{job_id}] Factorio container stopped: {_container_id}")
    except Exception as exc:
        logger.warning(f"[{job_id}] Could not stop Factorio container: {exc}")
