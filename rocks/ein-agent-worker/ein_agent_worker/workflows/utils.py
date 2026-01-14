"""Utility functions for workflows."""

from typing import Any, Dict, List

def format_alert_list(alerts: List[Dict[str, Any]]) -> str:
    """Format a list of alerts for agent consumption.

    Args:
        alerts: List of alert dictionaries from Alertmanager

    Returns:
        Formatted string with alert summaries
    """
    if not alerts:
        return "No alerts provided."

    alert_summaries = []
    for i, alert in enumerate(alerts, 1):
        summary = f"Alert {i}: {format_alert_summary(alert)}"
        alert_summaries.append(summary)

    return "\n\n".join(alert_summaries)


def format_alert_summary(alert: Dict[str, Any]) -> str:
    """Format an alert into a human-readable summary.

    Args:
        alert: Alert dictionary

    Returns:
        Formatted alert summary string
    """
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    summary_lines = [
        f"- **Alert:** {alert.get('alertname', 'N/A')}",
        f"- **Status:** {alert.get('status', 'N/A')}",
        f"- **Severity:** {labels.get('severity', 'N/A')}",
        f"- **Starts At:** {alert.get('starts_at', 'N/A')}",
    ]

    # Add fingerprint for identification
    if alert.get('fingerprint'):
        summary_lines.append(f"- **Fingerprint:** {alert['fingerprint']}")

    # Add common resource labels
    resource_keys = ["node", "namespace", "pod", "deployment", "statefulset", "daemonset", "job", "instance"]
    for key in resource_keys:
        if labels.get(key):
            summary_lines.append(f"- **{key.capitalize()}:** {labels[key]}")

    # Add description/summary from annotations
    if annotations.get('summary'):
        summary_lines.append(f"- **Summary:** {annotations['summary']}")
    if annotations.get('description'):
        summary_lines.append(f"- **Description:** {annotations['description']}")

    return "\n".join(summary_lines)


def log_investigation_path(result: Any, logger: Any = None) -> None:
    """Log the complete investigation path from Runner result.

    Extracts handoff chain from Runner result and logs which agents
    were consulted and what tools they used.

    Args:
        result: RunResult from agents.Runner.run()
        logger: Logger to use (defaults to Python logging if not provided)
    """
    import logging as std_logging

    # Use provided logger, or fall back to standard Python logger
    log = logger if logger is not None else std_logging.getLogger(__name__)

    log.info("Investigation path:")

    if not hasattr(result, 'messages'):
        log.warning("Result has no messages attribute, cannot log path")
        return

    agent_count = {}
    tool_usage = {}

    for i, msg in enumerate(result.messages):
        # Track agent messages
        if hasattr(msg, 'role') and msg.role in ["agent", "user"]:
            sender = getattr(msg, 'sender', 'unknown')

            # Count agent invocations
            agent_count[sender] = agent_count.get(sender, 0) + 1

            log.debug(f"  Step {i}: Agent={sender}")

            # Log tool calls
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    tool_name = getattr(tool_call, 'name', 'unknown_tool')
                    tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1
                    log.debug(f"    - Tool: {tool_name}")

        # Track handoffs
        elif hasattr(msg, 'role') and msg.role == "handoff":
            source = getattr(msg, 'source_agent', 'unknown')
            target = getattr(msg, 'target_agent', 'unknown')
            log.info(f"  Step {i}: Handoff {source} → {target}")

    # Summary
    log.info(
        f"Investigation complete. "
        f"Total steps: {len(result.messages)}, "
        f"Agents: {dict(agent_count)}, "
        f"Tools used: {dict(tool_usage)}"
    )