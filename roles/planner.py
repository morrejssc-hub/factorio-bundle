"""Factorio planner role — surveys game state and produces an execution plan for worker."""

from yoitsu_contracts.bundle import JobSpec, role


@role(name="planner", description="Surveys initial game state and spawns a worker with a concrete execution plan")
def planner() -> JobSpec:
    return JobSpec(
        system_prompt="prompts/planner.md",
        tools=["factorio_rcon", "factorio_rcon_batch", "bash", "spawn_job"],
    )
