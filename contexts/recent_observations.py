"""Context provider: inject recent observation summaries for optimizer."""

from yoitsu_contracts.bundle import context_provider


@context_provider(name="recent_observations")
def provide_observations(goal: str) -> str:
    """Fetch recent observation events for this bundle."""
    import os

    from yoitsu_contracts.client import PasloeClient

    pasloe_url = os.environ.get("PASLOE_URL", "")
    bundle_url = os.environ.get("BUNDLE_URL", "")

    if not pasloe_url:
        return ""

    client = PasloeClient(pasloe_url, source_id="optimizer-context")
    try:
        events = client.query_events(type_prefix="observation.", limit=10)

        summaries = []
        for e in events.get("items", []):
            data = e.get("data", {})
            analyzer = data.get("analyzer_name", "unknown")
            suggestion = data.get("suggestion", "")
            repeated_tools = data.get("repeated_tools", {})
            if suggestion:
                summaries.append(f"- [{analyzer}] {suggestion}")
            elif repeated_tools:
                tools_str = ", ".join(f"{k}({v})" for k, v in repeated_tools.items())
                summaries.append(f"- [{analyzer}] Tool repetition detected: {tools_str}")

        if summaries:
            return "## Recent Observations\n\n" + "\n".join(summaries)
        return ""
    except Exception:
        return ""