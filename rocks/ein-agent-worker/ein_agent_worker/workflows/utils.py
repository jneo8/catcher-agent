"""Shared utility functions for workflows."""

import json
import re
from typing import Any, Dict, List

from temporalio import workflow
from temporalio.contrib import openai_agents


def load_mcp_servers() -> List[Any]:
    """Load MCP servers from workflow memo.

    Returns:
        List of MCP server instances
    """
    mcp_servers = []
    for name in workflow.memo_value("mcp_servers", default=[]):
        try:
            mcp_servers.append(openai_agents.workflow.stateless_mcp_server(name))
        except Exception as e:
            workflow.logger.warning(f"Failed to load MCP server '{name}': {e}")
    return mcp_servers


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

    # Add common resource labels
    resource_keys = ["node", "namespace", "pod", "deployment", "statefulset", "daemonset", "job"]
    for key in resource_keys:
        if labels.get(key):
            summary_lines.append(f"- **{key.capitalize()}:** {labels[key]}")

    if annotations.get('summary'):
        summary_lines.append(f"- **Summary:** {annotations['summary']}")

    return "\n".join(summary_lines)


def extract_json_from_output(output: str) -> str:
    """Extract JSON from agent output, handling markdown code blocks.

    Args:
        output: Raw agent output that may contain JSON

    Returns:
        Extracted JSON string
    """
    output = output.strip()

    # Remove markdown code blocks if present
    if output.startswith("```"):
        lines = output.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove last line (```)
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        output = "\n".join(lines).strip()

    # Try to extract JSON from anywhere in the output using regex
    json_match = re.search(r'\{.*\}', output, re.DOTALL)
    if json_match:
        output = json_match.group(0)

    return output


def extract_resource_info(alert: Dict[str, Any]) -> Dict[str, str]:
    """Extract resource information from alert labels.

    Args:
        alert: Alert dictionary

    Returns:
        Dictionary with resource_name and scope
    """
    labels = alert.get("labels", {})

    # Try to find a resource identifier in common label fields
    resource_name = (
        labels.get("pod") or
        labels.get("node") or
        labels.get("service") or
        labels.get("deployment") or
        labels.get("statefulset") or
        labels.get("daemonset") or
        labels.get("job") or
        "unknown"
    )

    scope = labels.get("namespace", "")

    return {
        "resource_name": resource_name,
        "scope": scope
    }
