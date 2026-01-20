"""Shared Context Tools for the Blackboard pattern.

These tools allow agents to read and write findings to a shared context,
enabling cross-agent correlation and preventing redundant investigations.
"""

from typing import Optional, Tuple, Callable, List
from agents import function_tool
from temporalio import workflow

from ein_agent_worker.models import SharedContext


def create_shared_context_tools(
    shared_context: SharedContext,
    agent_name: str
) -> Tuple[Callable, Callable]:
    """Create shared context tools bound to a specific context and agent.

    Args:
        shared_context: The SharedContext instance to use
        agent_name: Name of the agent using these tools

    Returns:
        Tuple of (update_shared_context, get_shared_context) function tools
    """

    @function_tool
    def update_shared_context(
        key: str,
        value: str,
        confidence: float
    ) -> str:
        """Record a finding to the shared context (Blackboard).

        Use this tool when you discover important information during investigation.
        Other agents can see your findings and avoid redundant work.

        Args:
            key: Resource identifier (e.g., 'host:compute-01', 'pod:nginx-abc123',
                 'service:api-gateway', 'node:worker-1', 'osd:osd.5')
            value: The observed status or identified issue (e.g., 'disk failure detected',
                   'high CPU utilization at 95%', 'connection refused to database')
            confidence: How certain you are about this finding (0.0 to 1.0).
                       Use 0.9-1.0 for confirmed root causes,
                       0.7-0.8 for likely causes,
                       0.5-0.6 for possible causes,
                       below 0.5 for speculative observations.

        Returns:
            Confirmation message
        """
        workflow.logger.info(
            f"[Tool Call] update_shared_context called by {agent_name}: "
            f"key={key}, value={value}, confidence={confidence}"
        )

        finding = shared_context.add_finding(
            key=key,
            value=value,
            confidence=confidence,
            agent_name=agent_name,
            timestamp=workflow.now()
        )

        workflow.logger.info(
            f"[Tool Result] update_shared_context: Finding recorded for {key}"
        )

        return (
            f"Finding recorded: [{agent_name}] {key}: {value} "
            f"(confidence: {confidence:.2f})"
        )

    @function_tool
    def get_shared_context(filter_key: Optional[str] = None) -> str:
        """Retrieve findings from the shared context (Blackboard).

        Call this at the START of your investigation to check if other agents
        have already identified a root cause. If a high-confidence finding exists
        for your resource, you may be able to skip redundant investigation.

        Args:
            filter_key: Optional filter to narrow results. Examples:
                       - 'host:' to get all host-related findings
                       - 'pod:nginx' to get findings for nginx pods
                       - 'osd:' for all OSD findings
                       - None to get all findings

        Returns:
            Summary of relevant findings from other agents
        """
        workflow.logger.info(
            f"[Tool Call] get_shared_context called by {agent_name}: "
            f"filter_key={filter_key}"
        )

        findings = shared_context.get_findings(filter_key=filter_key)

        workflow.logger.info(
            f"[Tool Result] get_shared_context: Found {len(findings)} findings"
        )

        if not findings:
            if filter_key:
                return f"No findings in shared context matching '{filter_key}'."
            return "No findings in shared context yet. You are the first to investigate."

        lines = [f"=== Shared Context ({len(findings)} findings) ==="]

        # Group by confidence level
        high_conf = [f for f in findings if f.confidence >= 0.8]
        medium_conf = [f for f in findings if 0.5 <= f.confidence < 0.8]
        low_conf = [f for f in findings if f.confidence < 0.5]

        if high_conf:
            lines.append("\n** HIGH CONFIDENCE (likely root causes) **")
            for f in high_conf:
                lines.append(f"  - [{f.agent_name}] {f.key}: {f.value} ({f.confidence:.2f})")

        if medium_conf:
            lines.append("\n** MEDIUM CONFIDENCE **")
            for f in medium_conf:
                lines.append(f"  - [{f.agent_name}] {f.key}: {f.value} ({f.confidence:.2f})")

        if low_conf:
            lines.append("\n** LOW CONFIDENCE (observations) **")
            for f in low_conf:
                lines.append(f"  - [{f.agent_name}] {f.key}: {f.value} ({f.confidence:.2f})")

        return "\n".join(lines)

    return update_shared_context, get_shared_context
