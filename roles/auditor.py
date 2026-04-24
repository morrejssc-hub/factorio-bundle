"""Factorio audit role.

The audit verdict is produced by factorio_server.finalize from the fixed
acceptance Lua; the agent loop is intentionally a no-op.
"""

from yoitsu_contracts.bundle import JobSpec, role


@role(name="auditor", description="Runs deterministic Factorio acceptance checks")
def auditor() -> JobSpec:
    return JobSpec(
        system_prompt="__YOITSU_NOOP__",
        tools=[],
    )
