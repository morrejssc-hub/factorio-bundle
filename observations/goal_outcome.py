"""Analyzer: summarize job outcome and LLM usage stats."""


def analyze(*, events: list[dict], job_id: str) -> dict | None:
    completed = any(e.get("type") == "agent.job.completed" for e in events)
    failed = any(e.get("type") == "agent.job.failed" for e in events)

    llm_requests = [e for e in events if e.get("type") == "agent.llm.request"]
    llm_responses = [e for e in events if e.get("type") == "agent.llm.response"]

    total_input_tokens = sum(
        e["data"].get("input_tokens", 0) or 0 for e in llm_responses
    )
    total_output_tokens = sum(
        e["data"].get("output_tokens", 0) or 0 for e in llm_responses
    )

    outcome = "completed" if completed else ("failed" if failed else "unknown")

    return {
        "outcome": outcome,
        "llm_turns": len(llm_requests),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
    }
