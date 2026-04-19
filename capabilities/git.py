"""Git capability for target workspace lifecycle.

setup: clone target repo
finalize: push target changes (role-based)

Events emitted (canonical):
- coordinator.capability.completed  data.name encodes sub-operation
- coordinator.capability.failed     data.name encodes sub-operation
"""
from __future__ import annotations

import logging
import os

from coordinator.capability import CapabilityContext, CapabilityResult, EventSpec
from coordinator.git_ops import git_clone, git_push, read_head_sha

logger = logging.getLogger(__name__)

_PUSH_ROLES = ("worker", "architect")


def setup(ctx: CapabilityContext) -> CapabilityResult:
    events: list[EventSpec] = []

    if not ctx.target_path:
        return CapabilityResult(ok=False, events=events, error="target_path not provided")

    target_repo = ctx.target_repo or os.environ.get("TARGET_REPO", "")
    if not target_repo:
        return CapabilityResult(ok=False, events=events, error="TARGET_REPO not available")

    try:
        git_clone(target_repo, str(ctx.target_path))
        target_sha = read_head_sha(ctx.target_path)
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "git.cloned", "job_id": ctx.job_id,
                  "target_repo": target_repo, "target_sha": (target_sha or "")[:12]},
        ))
        logger.info(f"[{ctx.job_id}] Git: cloned target @ {(target_sha or '')[:12]}")
        return CapabilityResult(ok=True, events=events)

    except Exception as exc:
        logger.error(f"[{ctx.job_id}] Git setup failed: {exc}")
        events.append(EventSpec(
            type="coordinator.capability.failed",
            data={"name": "git.clone_failed", "job_id": ctx.job_id, "error": str(exc)},
        ))
        return CapabilityResult(ok=False, events=events, error=str(exc))


def finalize(ctx: CapabilityContext) -> CapabilityResult:
    events: list[EventSpec] = []

    if not ctx.target_path:
        return CapabilityResult(ok=True, events=events)

    target_repo = ctx.target_repo or os.environ.get("TARGET_REPO", "")
    if not target_repo:
        return CapabilityResult(ok=True, events=events)

    if ctx.role not in _PUSH_ROLES:
        logger.info(f"[{ctx.job_id}] Git: role={ctx.role} skips push")
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "git.push_skipped", "job_id": ctx.job_id,
                  "role": ctx.role, "reason": "role_not_permitted_to_push"},
        ))
        return CapabilityResult(ok=True, events=events)

    try:
        git_push(ctx.target_path, target_repo, branch="main")
        target_sha = read_head_sha(ctx.target_path)
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "git.pushed", "job_id": ctx.job_id,
                  "target_repo": target_repo, "target_sha": (target_sha or "")[:12]},
        ))
        logger.info(f"[{ctx.job_id}] Git: pushed target @ {(target_sha or '')[:12]}")
        return CapabilityResult(ok=True, events=events)

    except Exception as exc:
        logger.warning(f"[{ctx.job_id}] Git finalize push failed: {exc}")
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "git.push_failed", "job_id": ctx.job_id, "error": str(exc)},
        ))
        return CapabilityResult(ok=True, events=events)  # soft failure
