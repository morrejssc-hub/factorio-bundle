"""Factorio worker role — uses RCON to automate in-game tasks."""

from yoitsu_contracts.bundle import JobSpec, role


@role(name="worker", description="Factorio automation worker with RCON access")
def worker() -> JobSpec:
    return JobSpec(
        system_prompt="prompts/worker.md",
        tools=["factorio_rcon", "bash"],
    )
