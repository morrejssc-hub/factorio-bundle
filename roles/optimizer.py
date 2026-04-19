"""Factorio bundle optimizer role."""

from yoitsu_contracts.bundle import JobSpec, role


@role(name="optimizer", description="Reviews observations and proposes Factorio bundle improvements")
def optimizer() -> JobSpec:
    return JobSpec(
        system_prompt="prompts/optimizer.md",
        tools=["bash", "spawn_job"],
        context_sections=["recent_observations"],
    )
