"""Git capability for target workspace lifecycle.

This capability handles:
- setup: clone target repo, configure git identity
- finalize: push target changes (role-based decision)

Capabilities are versioned with the bundle SHA, ensuring reproducible behavior.
Bundles that need git should include this file in their capabilities/ directory.

Events emitted:
- capability.git.cloned: target repo cloned
- capability.git.pushed: target changes pushed (with commit sha)
- capability.git.push_skipped: role not permitted to push
- capability.git.push_failed: push error (soft failure)
"""
from __future__ import annotations

import logging
import os

from coordinator.capability import CapabilityContext, CapabilityResult, EventSpec
from coordinator.git_ops import git_clone, git_push, read_head_sha

logger = logging.getLogger(__name__)


class GitCapabilityConfig:
    """Configuration for git capability (can be extended in future)."""
    # Role-based push behavior:
    # - "worker": always push if changes exist
    # - "reviewer": don't push (just review changes)
    # Future: could be configurable per bundle
    push_roles = ("worker", "architect")


def setup(ctx: CapabilityContext) -> CapabilityResult:
    """Clone target repo and configure git identity.

    The target_path is provided by coordinator; this capability just
    performs the clone and sets up the working environment.
    """
    events: list[EventSpec] = []

    if not ctx.target_path:
        return CapabilityResult(
            ok=False,
            events=events,
            error="target_path not provided in context",
        )

    # Get target_repo from context (preferred) or environment (fallback)
    target_repo = ctx.target_repo
    if not target_repo:
        target_repo = os.environ.get("TARGET_REPO", "")
    if not target_repo:
        return CapabilityResult(
            ok=False,
            events=events,
            error="TARGET_REPO not available (not in context or env)",
        )

    try:
        # Clone target repo
        git_clone(target_repo, str(ctx.target_path))
        target_sha = read_head_sha(ctx.target_path)

        events.append(EventSpec(
            type="capability.git.cloned",
            data={
                "job_id": ctx.job_id,
                "target_repo": target_repo,
                "target_sha": target_sha[:12] if target_sha else "",
            },
        ))

        logger.info(f"[{ctx.job_id}] Git capability: cloned target @ {target_sha[:12] if target_sha else 'empty'}")
        return CapabilityResult(ok=True, events=events)

    except Exception as exc:
        logger.error(f"[{ctx.job_id}] Git capability setup failed: {exc}")
        return CapabilityResult(
            ok=False,
            events=events,
            error=str(exc),
        )


def finalize(ctx: CapabilityContext) -> CapabilityResult:
    """Push target changes if role permits.

    Role-based push behavior:
    - worker/architect: push if there are changes
    - reviewer: don't push (just review)

    Returns commit sha in event if pushed.
    """
    events: list[EventSpec] = []

    if not ctx.target_path:
        return CapabilityResult(ok=True, events=events)  # Nothing to do

    # Get target_repo from context (preferred) or environment (fallback)
    target_repo = ctx.target_repo
    if not target_repo:
        target_repo = os.environ.get("TARGET_REPO", "")
    if not target_repo:
        return CapabilityResult(ok=True, events=events)  # Nothing to push

    # Role-based push decision
    config = GitCapabilityConfig()
    should_push = ctx.role in config.push_roles

    if not should_push:
        logger.info(f"[{ctx.job_id}] Git capability: role={ctx.role} skips push")
        events.append(EventSpec(
            type="capability.git.push_skipped",
            data={
                "job_id": ctx.job_id,
                "role": ctx.role,
                "reason": "role_not_permitted_to_push",
            },
        ))
        return CapabilityResult(ok=True, events=events)

    try:
        # Push target
        git_push(ctx.target_path, target_repo, branch="main")

        target_sha = read_head_sha(ctx.target_path)
        events.append(EventSpec(
            type="capability.git.pushed",
            data={
                "job_id": ctx.job_id,
                "target_repo": target_repo,
                "target_sha": target_sha[:12] if target_sha else "",
            },
        ))

        logger.info(f"[{ctx.job_id}] Git capability: pushed target @ {target_sha[:12] if target_sha else 'empty'}")
        return CapabilityResult(ok=True, events=events)

    except Exception as exc:
        logger.warning(f"[{ctx.job_id}] Git capability finalize failed: {exc}")
        # Push failure is non-critical - job may have succeeded
        events.append(EventSpec(
            type="capability.git.push_failed",
            data={
                "job_id": ctx.job_id,
                "error": str(exc),
            },
        ))
        return CapabilityResult(ok=True, events=events)  # Soft failure