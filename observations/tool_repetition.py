"""Analyzer: flag jobs where the same tool was called more than N times total."""

from collections import Counter


def analyze(*, events: list[dict], job_id: str) -> dict | None:
    tool_calls = [
        e["data"].get("tool_name", "")
        for e in events
        if e.get("type") == "agent.tool.called"
    ]
    if not tool_calls:
        return None

    counts = Counter(tool_calls)
    repeated = {name: count for name, count in counts.items() if count > 3}
    if not repeated:
        return None

    return {
        "repeated_tools": repeated,
        "total_tool_calls": len(tool_calls),
        "suggestion": (
            f"Tools {list(repeated.keys())} were called excessively across the job. "
            "Consider adding guidance or abstracting the repeated pattern."
        ),
    }
