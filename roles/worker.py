"""Factorio worker role — uses structured Factorio script primitives."""

from yoitsu_contracts.bundle import JobSpec, role


@role(name="worker", description="Factorio automation worker with structured script access")
def worker() -> JobSpec:
    return JobSpec(
        system_prompt="prompts/worker.md",
        tools=["factorio_script"],
    )
