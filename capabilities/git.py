"""Git capability for workspace lifecycle.

setup: clone workspace repo
finalize: push workspace changes (role-based)

Events emitted (canonical):
- coordinator.capability.completed  data.name encodes sub-operation
- coordinator.capability.failed     data.name encodes sub-operation
"""
from __future__ import annotations

import logging
import os

from coordinator.capability import CapabilityContext, CapabilityResult, EventSpec
from coordinator.git_ops import (
    create_pull_request,
    enable_pr_auto_merge,
    git_checkout_work_branch,
    git_clone,
    git_push,
    read_head_sha,
)

logger = logging.getLogger(__name__)

_PUSH_ROLES = ("worker", "architect", "implementer")
_BASE_BRANCH = "main"


def _work_branch(job_id: str) -> str:
    return f"job/{job_id}"


def _pr_body(ctx: CapabilityContext) -> str:
    summary = getattr(ctx.agent_result, "summary", "") if ctx.agent_result else ""
    return summary or "Automated changes from coordinator job."


def setup(ctx: CapabilityContext) -> CapabilityResult:
    events: list[EventSpec] = []

    if not ctx.workspace_path:
        return CapabilityResult(ok=False, events=events, error="workspace_path not provided")

    workspace_repo = ctx.workspace_repo or os.environ.get("WORKSPACE_REPO", "")
    if not workspace_repo:
        return CapabilityResult(ok=False, events=events, error="WORKSPACE_REPO not available")

    try:
        git_clone(workspace_repo, str(ctx.workspace_path))
        branch_name = git_checkout_work_branch(ctx.workspace_path, ctx.job_id)
        workspace_sha = read_head_sha(ctx.workspace_path)
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "git.cloned", "job_id": ctx.job_id,
                  "workspace_repo": workspace_repo, "workspace_sha": (workspace_sha or "")[:12],
                  "branch": branch_name},
        ))
        logger.info(
            f"[{ctx.job_id}] Git: cloned workspace @ {(workspace_sha or '')[:12]} "
            f"on {branch_name}"
        )
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

    if not ctx.workspace_path:
        return CapabilityResult(ok=True, events=events)

    workspace_repo = ctx.workspace_repo or os.environ.get("WORKSPACE_REPO", "")
    if not workspace_repo:
        return CapabilityResult(ok=True, events=events)

    if ctx.role not in _PUSH_ROLES:
        logger.info(f"[{ctx.job_id}] Git: role={ctx.role} skips push")
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "git.push_skipped", "job_id": ctx.job_id,
                  "role": ctx.role, "reason": "role_not_permitted_to_push"},
        ))
        return CapabilityResult(ok=True, events=events)

    branch_name = _work_branch(ctx.job_id)
    operation_name = "git.push_failed"
    try:
        git_push(ctx.workspace_path, workspace_repo, branch=branch_name)
        workspace_sha = read_head_sha(ctx.workspace_path)
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={"name": "git.pushed", "job_id": ctx.job_id,
                  "workspace_repo": workspace_repo, "workspace_sha": (workspace_sha or "")[:12],
                  "branch": branch_name},
        ))
        logger.info(
            f"[{ctx.job_id}] Git: pushed workspace @ {(workspace_sha or '')[:12]} "
            f"to {branch_name}"
        )

        operation_name = "git.pr_open_failed"
        pr = create_pull_request(
            remote_url=workspace_repo,
            head=branch_name,
            base=_BASE_BRANCH,
            title=f"[{ctx.job_id}] Automated changes",
            body=_pr_body(ctx),
        )
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={
                "name": "git.pr_opened",
                "job_id": ctx.job_id,
                "workspace_repo": workspace_repo,
                "branch": branch_name,
                "base": _BASE_BRANCH,
                "pr_url": pr["html_url"],
                "pr_number": pr["number"],
            },
        ))
        logger.info(f"[{ctx.job_id}] Git: opened PR {pr['html_url']}")

        operation_name = "git.auto_merge_failed"
        enable_pr_auto_merge(str(pr["node_id"]), merge_method="SQUASH")
        events.append(EventSpec(
            type="coordinator.capability.completed",
            data={
                "name": "git.auto_merge_enabled",
                "job_id": ctx.job_id,
                "workspace_repo": workspace_repo,
                "branch": branch_name,
                "base": _BASE_BRANCH,
                "pr_url": pr["html_url"],
                "pr_number": pr["number"],
                "merge_method": "SQUASH",
            },
        ))
        logger.info(f"[{ctx.job_id}] Git: enabled auto-merge for PR {pr['number']}")
        return CapabilityResult(ok=True, events=events)

    except Exception as exc:
        logger.warning(f"[{ctx.job_id}] Git finalize failed ({operation_name}): {exc}")
        events.append(EventSpec(
            type="coordinator.capability.failed",
            data={
                "name": operation_name,
                "job_id": ctx.job_id,
                "workspace_repo": workspace_repo,
                "branch": branch_name,
                "error": str(exc),
            },
        ))
        return CapabilityResult(ok=False, events=events, error=str(exc))
