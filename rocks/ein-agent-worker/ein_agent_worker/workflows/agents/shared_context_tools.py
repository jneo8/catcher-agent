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
) -> Tuple[Callable, Callable, Callable]:
    """Create shared context tools bound to a specific context and agent.

    Args:
        shared_context: The SharedContext instance to use
        agent_name: Name of the agent using these tools

    Returns:
        Tuple of (update_shared_context, get_shared_context, print_findings_report) function tools
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

    @function_tool
    def print_findings_report(
        title: str = "Investigation Findings Report",
        include_recommendations: bool = True
    ) -> str:
        """Generate a formatted report of all investigation findings.

        Use this tool when you want to present a comprehensive summary of the
        investigation to the user. This creates a well-structured report that
        groups findings by confidence level and includes actionable insights.

        Args:
            title: The title for the report header
            include_recommendations: Whether to include recommendations based on findings

        Returns:
            A formatted report suitable for presenting to users
        """
        workflow.logger.info(
            f"[Tool Call] print_findings_report called by {agent_name}: "
            f"title={title}, include_recommendations={include_recommendations}"
        )

        findings = shared_context.findings

        if not findings:
            return (
                f"# {title}\n\n"
                "No findings have been recorded yet.\n\n"
                "Use the investigation tools to gather information first."
            )

        # Group findings by confidence
        root_causes = [f for f in findings if f.confidence >= 0.8]
        likely_issues = [f for f in findings if 0.5 <= f.confidence < 0.8]
        observations = [f for f in findings if f.confidence < 0.5]

        # Group by resource type
        resource_groups: dict[str, list] = {}
        for f in findings:
            resource_type = f.key.split(":")[0] if ":" in f.key else "other"
            if resource_type not in resource_groups:
                resource_groups[resource_type] = []
            resource_groups[resource_type].append(f)

        lines = [
            f"# {title}",
            "",
            f"**Generated by:** {agent_name}",
            f"**Total Findings:** {len(findings)}",
            "",
        ]

        # Root Causes Section
        if root_causes:
            lines.extend([
                "## Root Causes Identified",
                "",
                "The following issues have been identified with high confidence as root causes:",
                "",
            ])
            for f in sorted(root_causes, key=lambda x: x.confidence, reverse=True):
                confidence_pct = int(f.confidence * 100)
                lines.append(f"### {f.key}")
                lines.append(f"- **Issue:** {f.value}")
                lines.append(f"- **Confidence:** {confidence_pct}%")
                lines.append(f"- **Identified by:** {f.agent_name}")
                if f.timestamp:
                    lines.append(f"- **Time:** {f.timestamp.isoformat()}")
                lines.append("")

        # Likely Issues Section
        if likely_issues:
            lines.extend([
                "## Likely Contributing Factors",
                "",
                "These issues may be contributing to the problem:",
                "",
            ])
            for f in sorted(likely_issues, key=lambda x: x.confidence, reverse=True):
                confidence_pct = int(f.confidence * 100)
                lines.append(f"- **{f.key}:** {f.value} ({confidence_pct}% confidence, {f.agent_name})")
            lines.append("")

        # Observations Section
        if observations:
            lines.extend([
                "## Additional Observations",
                "",
                "The following observations were noted during investigation:",
                "",
            ])
            for f in observations:
                confidence_pct = int(f.confidence * 100)
                lines.append(f"- **{f.key}:** {f.value} ({confidence_pct}% confidence)")
            lines.append("")

        # Affected Resources Summary
        if len(resource_groups) > 1:
            lines.extend([
                "## Affected Resources Summary",
                "",
            ])
            for resource_type, group_findings in sorted(resource_groups.items()):
                high_conf_count = sum(1 for f in group_findings if f.confidence >= 0.8)
                lines.append(
                    f"- **{resource_type.capitalize()}:** {len(group_findings)} findings "
                    f"({high_conf_count} high confidence)"
                )
            lines.append("")

        # Recommendations Section
        if include_recommendations and root_causes:
            lines.extend([
                "## Recommended Actions",
                "",
            ])
            for i, f in enumerate(root_causes[:5], 1):  # Top 5 root causes
                lines.append(f"{i}. Investigate and resolve: **{f.key}**")
                lines.append(f"   - Issue: {f.value}")
            lines.append("")

        lines.extend([
            "---",
            "*This report was automatically generated from investigation findings.*"
        ])

        report = "\n".join(lines)

        workflow.logger.info(
            f"[Tool Result] print_findings_report: Generated report with "
            f"{len(root_causes)} root causes, {len(likely_issues)} likely issues, "
            f"{len(observations)} observations"
        )

        return report

    return update_shared_context, get_shared_context, print_findings_report
