"""Factorio bundle implementer role."""

from yoitsu_contracts.bundle import JobSpec, role


@role(name="implementer", description="Applies an approved improvement to the Factorio bundle")
def implementer() -> JobSpec:
    return JobSpec(
        system_prompt="prompts/implementer.md",
        tools=["bash"],
    )
