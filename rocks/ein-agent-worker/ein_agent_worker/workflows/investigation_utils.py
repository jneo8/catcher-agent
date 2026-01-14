"""Utility functions for multi-agent investigation workflows."""

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple

from temporalio import workflow

from ein_agent_worker.models.investigation import AlertFindings, ContextAgentState


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
        labels.get("instance") or
        labels.get("node") or
        labels.get("service") or
        labels.get("deployment") or
        labels.get("statefulset") or
        labels.get("daemonset") or
        labels.get("job") or
        labels.get("alertname", "unknown")  # Fallback to alertname
    )

    scope = labels.get("namespace") or labels.get("project") or labels.get("region") or ""

    return {
        "resource_name": resource_name,
        "scope": scope
    }


def parse_alert_findings(
    output: str,
    alert: Dict[str, Any],
    round_number: int = 1,
    logger: Any = None
) -> AlertFindings:
    """Parse agent output into structured AlertFindings.

    Attempts to extract structured information from the agent's output.
    Falls back to unstructured parsing if JSON extraction fails.

    Args:
        output: Raw agent output string
        alert: Original alert dictionary
        round_number: Current investigation round
        logger: Logger to use (defaults to Python logging if not provided)

    Returns:
        AlertFindings object
    """
    alertname = alert.get("alertname", "unknown")
    alert_id = alert.get("fingerprint", alertname)
    timestamp = alert.get("starts_at", "")
    resource_info = extract_resource_info(alert)

    # Try to extract JSON from output
    try:
        # Look for JSON in the output
        json_match = None
        if output.strip().startswith("{"):
            json_match = output.strip()
        else:
            # Try to find JSON in markdown code blocks or elsewhere
            import re
            match = re.search(r'\{.*\}', output, re.DOTALL)
            if match:
                json_match = match.group(0)

        if json_match:
            data = json.loads(json_match)

            return AlertFindings(
                alertname=alertname,
                alert_id=alert_id,
                timestamp=timestamp,
                root_cause_assessment=data.get("root_cause_assessment", data.get("root_cause", "Unknown")),
                affected_layers=data.get("affected_layers", []),
                affected_resources=data.get("affected_resources", [resource_info["resource_name"]]),
                scope=data.get("scope", resource_info["scope"]),
                confidence=float(data.get("confidence", 0.5)),
                specialist_findings=data.get("specialist_findings", {}),
                round_number=round_number,
                investigation_path=data.get("investigation_path", [])
            )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        import logging as std_logging
        # Use provided logger, or fall back to standard Python logger
        log = logger if logger is not None else std_logging.getLogger(__name__)
        log.warning(f"Failed to parse structured findings: {e}, falling back to text parsing")

    # Fallback: Create findings from unstructured text
    return AlertFindings(
        alertname=alertname,
        alert_id=alert_id,
        timestamp=timestamp,
        root_cause_assessment=output[:500] if len(output) > 500 else output,  # Truncate long outputs
        affected_layers=["unknown"],
        affected_resources=[resource_info["resource_name"]],
        scope=resource_info["scope"],
        confidence=0.5,  # Default moderate confidence
        specialist_findings={},
        round_number=round_number,
        investigation_path=[]
    )


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


def extract_confidence(output: str) -> float:
    """Extract confidence score from agent output.

    Looks for confidence indicators in the output text.

    Args:
        output: Agent output string

    Returns:
        Confidence score (0.0 to 1.0), defaults to 0.5
    """
    try:
        # Try JSON first
        import re
        json_match = re.search(r'\{.*\}', output, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            if "confidence" in data:
                return float(data["confidence"])

        # Look for confidence mentions in text
        confidence_patterns = [
            r"confidence[:\s]+(\d+\.?\d*)%?",
            r"confidence[:\s]+(\d+\.?\d*)/1\.?0",
        ]

        for pattern in confidence_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                # Normalize to 0.0-1.0 range
                if value > 1.0:
                    value = value / 100.0
                return min(max(value, 0.0), 1.0)

    except (json.JSONDecodeError, ValueError, AttributeError):
        pass

    # Default moderate confidence
    return 0.5


# ============================================================================
# Phase 2: Cross-Alert Context Building Utilities
# ============================================================================


def group_by_shared_infrastructure(findings: List[AlertFindings]) -> Dict[str, List[AlertFindings]]:
    """Group alerts by shared infrastructure components.

    Groups findings that share resources or are in the same scope
    (e.g., same namespace, node, region, etc.).

    Args:
        findings: List of AlertFindings from round 1

    Returns:
        Dictionary mapping resource identifiers to lists of related findings
    """
    groups = defaultdict(list)

    for finding in findings:
        # Group by scope (namespace, region, etc.)
        if finding.scope:
            groups[f"scope:{finding.scope}"].append(finding)

        # Group by affected resources
        for resource in finding.affected_resources:
            groups[f"resource:{resource}"].append(finding)

        # Group by affected layers (infrastructure, application, storage, etc.)
        for layer in finding.affected_layers:
            groups[f"layer:{layer}"].append(finding)

    # Filter out single-alert groups (not shared)
    shared_groups = {k: v for k, v in groups.items() if len(v) > 1}

    return shared_groups


def detect_temporal_patterns(findings: List[AlertFindings]) -> List[Dict[str, Any]]:
    """Detect temporal patterns in alert timing.

    Identifies:
    - Alerts that started at similar times (potential common cause)
    - Cascade patterns (alerts triggered in sequence)

    Args:
        findings: List of AlertFindings with timestamps

    Returns:
        List of pattern dictionaries describing temporal relationships
    """
    patterns = []

    # Parse timestamps
    timestamped_findings = []
    for finding in findings:
        try:
            if finding.timestamp:
                # Handle various timestamp formats
                ts = finding.timestamp
                if isinstance(ts, str):
                    # Try common formats
                    for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"]:
                        try:
                            dt = datetime.strptime(ts, fmt)
                            timestamped_findings.append((dt, finding))
                            break
                        except ValueError:
                            continue
        except Exception as e:
            workflow.logger.debug(f"Could not parse timestamp for {finding.alertname}: {e}")

    # Sort by timestamp
    timestamped_findings.sort(key=lambda x: x[0])

    # Detect simultaneous alerts (within 30 seconds)
    simultaneous_threshold_seconds = 30
    simultaneous_groups = []

    i = 0
    while i < len(timestamped_findings):
        group = [timestamped_findings[i]]
        j = i + 1

        while j < len(timestamped_findings):
            time_diff = (timestamped_findings[j][0] - timestamped_findings[i][0]).total_seconds()
            if time_diff <= simultaneous_threshold_seconds:
                group.append(timestamped_findings[j])
                j += 1
            else:
                break

        if len(group) > 1:
            simultaneous_groups.append(group)

        i = j if j > i + 1 else i + 1

    for group in simultaneous_groups:
        patterns.append({
            "type": "simultaneous",
            "alert_ids": [f.alert_id for _, f in group],
            "timestamp": group[0][0].isoformat(),
            "count": len(group),
            "description": f"{len(group)} alerts triggered within {simultaneous_threshold_seconds}s"
        })

    # Detect cascade patterns (sequential alerts)
    if len(timestamped_findings) >= 3:
        cascade_threshold_seconds = 300  # 5 minutes

        for i in range(len(timestamped_findings) - 2):
            sequence = [timestamped_findings[i]]

            for j in range(i + 1, min(i + 5, len(timestamped_findings))):
                time_diff = (timestamped_findings[j][0] - timestamped_findings[j-1][0]).total_seconds()
                if 0 < time_diff <= cascade_threshold_seconds:
                    sequence.append(timestamped_findings[j])
                else:
                    break

            if len(sequence) >= 3:
                patterns.append({
                    "type": "cascade",
                    "alert_ids": [f.alert_id for _, f in sequence],
                    "start_time": sequence[0][0].isoformat(),
                    "end_time": sequence[-1][0].isoformat(),
                    "duration_seconds": (sequence[-1][0] - sequence[0][0]).total_seconds(),
                    "description": f"Cascade of {len(sequence)} alerts over {(sequence[-1][0] - sequence[0][0]).total_seconds():.0f}s"
                })

    return patterns


def detect_cascade_patterns(findings: List[AlertFindings]) -> List[Dict[str, Any]]:
    """Detect dependency cascade patterns between alerts.

    Identifies when alerts in dependent infrastructure layers suggest a cascade failure
    (e.g., storage → compute → application).

    Args:
        findings: List of AlertFindings with layer information

    Returns:
        List of cascade pattern dictionaries
    """
    # Define common dependency relationships between layers
    # Format: (upstream_layer, downstream_layer)
    layer_dependencies = [
        ("infrastructure", "compute"),
        ("infrastructure", "storage"),
        ("storage", "compute"),
        ("compute", "application"),
        ("storage", "application"),
        ("network", "compute"),
        ("network", "application"),
    ]

    cascades = []

    # Group findings by layer
    layer_map = defaultdict(list)
    for finding in findings:
        for layer in finding.affected_layers:
            layer_map[layer.lower()].append(finding)

    # Check for cascade patterns
    for upstream, downstream in layer_dependencies:
        upstream_findings = layer_map.get(upstream, [])
        downstream_findings = layer_map.get(downstream, [])

        if upstream_findings and downstream_findings:
            cascades.append({
                "type": "layer_cascade",
                "upstream_layer": upstream,
                "downstream_layer": downstream,
                "upstream_alert_ids": [f.alert_id for f in upstream_findings],
                "downstream_alert_ids": [f.alert_id for f in downstream_findings],
                "description": f"Potential cascade from {upstream} to {downstream} layer"
            })

    return cascades


def calculate_convergence(
    previous_findings: List[AlertFindings],
    current_findings: List[AlertFindings]
) -> float:
    """Calculate convergence between investigation rounds.

    Measures how much the findings have changed between rounds.
    Higher convergence (closer to 1.0) means findings are stabilizing.

    Args:
        previous_findings: Findings from previous round
        current_findings: Findings from current round

    Returns:
        Convergence score (0.0 to 1.0)
    """
    if not previous_findings or not current_findings:
        return 0.0

    # Create maps for comparison
    prev_map = {f.alert_id: f for f in previous_findings}
    curr_map = {f.alert_id: f for f in current_findings}

    # Calculate component convergence scores
    convergence_scores = []

    for alert_id in curr_map:
        if alert_id not in prev_map:
            continue

        prev = prev_map[alert_id]
        curr = curr_map[alert_id]

        # Root cause similarity (simple text comparison)
        rc_prev = prev.root_cause_assessment.lower()
        rc_curr = curr.root_cause_assessment.lower()
        rc_score = 1.0 if rc_prev == rc_curr else 0.5 if any(word in rc_curr for word in rc_prev.split()[:5]) else 0.0

        # Affected layers similarity
        prev_layers = set(prev.affected_layers)
        curr_layers = set(curr.affected_layers)
        if prev_layers or curr_layers:
            layer_score = len(prev_layers & curr_layers) / len(prev_layers | curr_layers)
        else:
            layer_score = 1.0

        # Confidence change (stable confidence = higher convergence)
        conf_diff = abs(prev.confidence - curr.confidence)
        conf_score = 1.0 - min(conf_diff, 1.0)

        # Weighted average
        alert_convergence = (rc_score * 0.5 + layer_score * 0.3 + conf_score * 0.2)
        convergence_scores.append(alert_convergence)

    # Overall convergence
    if convergence_scores:
        return sum(convergence_scores) / len(convergence_scores)
    else:
        return 0.0


def build_cross_alert_context(
    findings: List[AlertFindings],
    round_number: int
) -> ContextAgentState:
    """Build cross-alert context state for the CrossAlertContextAgent.

    This function creates the structured context that the CrossAlertContextAgent
    will use to answer queries from other agents.

    Args:
        findings: List of AlertFindings from the current round
        round_number: Current investigation round number

    Returns:
        ContextAgentState with structured cross-alert context
    """
    # Build indexes for fast lookup
    findings_by_resource = {}
    findings_by_scope = {}
    findings_by_layer = {}
    confidence_by_alert = {}

    for finding in findings:
        # Index by resource
        for resource in finding.affected_resources:
            if resource not in findings_by_resource:
                findings_by_resource[resource] = []
            findings_by_resource[resource].append(finding.alert_id)

        # Index by scope
        if finding.scope:
            if finding.scope not in findings_by_scope:
                findings_by_scope[finding.scope] = []
            findings_by_scope[finding.scope].append(finding.alert_id)

        # Index by layer
        for layer in finding.affected_layers:
            if layer not in findings_by_layer:
                findings_by_layer[layer] = []
            findings_by_layer[layer].append(finding.alert_id)

        # Track confidence by alert
        confidence_by_alert[finding.alert_id] = finding.confidence

    return ContextAgentState(
        round_number=round_number,
        all_findings=findings,
        findings_by_resource=findings_by_resource,
        findings_by_scope=findings_by_scope,
        findings_by_layer=findings_by_layer,
        confidence_by_alert=confidence_by_alert,
        previous_findings=None  # Could be populated for convergence tracking
    )


def format_findings_summary(findings: List[AlertFindings]) -> str:
    """Format findings into a concise summary for the CrossAlertContextAgent.

    Args:
        findings: List of AlertFindings to summarize

    Returns:
        Formatted string summarizing all findings
    """
    if not findings:
        return "No findings available."

    lines = []
    for i, finding in enumerate(findings, 1):
        lines.append(f"{i}. Alert: {finding.alertname} (ID: {finding.alert_id})")
        lines.append(f"   Root Cause: {finding.root_cause_assessment[:200]}")
        lines.append(f"   Layers: {', '.join(finding.affected_layers)}")
        lines.append(f"   Resources: {', '.join(finding.affected_resources[:3])}")  # Limit to 3
        lines.append(f"   Confidence: {finding.confidence:.2f}")
        lines.append("")

    return "\n".join(lines)


def format_resource_index(findings: List[AlertFindings]) -> str:
    """Format resource index for the CrossAlertContextAgent.

    Args:
        findings: List of AlertFindings

    Returns:
        Formatted resource index string
    """
    resource_map = defaultdict(list)

    for finding in findings:
        for resource in finding.affected_resources:
            resource_map[resource].append(f"{finding.alert_id} (conf: {finding.confidence:.2f})")

    if not resource_map:
        return "No resources indexed."

    lines = []
    for resource, alert_ids in sorted(resource_map.items()):
        lines.append(f"- {resource}: {', '.join(alert_ids)}")

    return "\n".join(lines)


def format_scope_index(findings: List[AlertFindings]) -> str:
    """Format scope index for the CrossAlertContextAgent.

    Args:
        findings: List of AlertFindings

    Returns:
        Formatted scope index string
    """
    scope_map = defaultdict(list)

    for finding in findings:
        if finding.scope:
            scope_map[finding.scope].append(f"{finding.alert_id} (conf: {finding.confidence:.2f})")

    if not scope_map:
        return "No scopes indexed."

    lines = []
    for scope, alert_ids in sorted(scope_map.items()):
        lines.append(f"- {scope}: {', '.join(alert_ids)}")

    return "\n".join(lines)


def format_layer_index(findings: List[AlertFindings]) -> str:
    """Format layer index for the CrossAlertContextAgent.

    Args:
        findings: List of AlertFindings

    Returns:
        Formatted layer index string
    """
    layer_map = defaultdict(list)

    for finding in findings:
        for layer in finding.affected_layers:
            layer_map[layer].append(f"{finding.alert_id} (conf: {finding.confidence:.2f})")

    if not layer_map:
        return "No layers indexed."

    lines = []
    for layer, alert_ids in sorted(layer_map.items()):
        lines.append(f"- {layer}: {', '.join(alert_ids)}")

    return "\n".join(lines)


def check_exit_conditions(
    findings: List[AlertFindings],
    previous_findings: List[AlertFindings],
    round_number: int,
    config: 'MultiRoundConfig'
) -> Tuple[bool, str]:
    """Check if investigation should exit based on exit conditions.

    Args:
        findings: Current round findings
        previous_findings: Previous round findings (empty if round 1)
        round_number: Current round number
        config: MultiRoundConfig with thresholds

    Returns:
        Tuple of (should_exit: bool, reason: str)
    """
    from ein_agent_worker.models.investigation import MultiRoundConfig

    # Condition 1: Max rounds reached
    if round_number >= config.max_rounds:
        return True, f"Max rounds ({config.max_rounds}) reached"

    # Condition 2: High confidence achieved
    confidences = [f.confidence for f in findings if f.confidence > 0]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    if avg_confidence >= config.confidence_threshold:
        return True, f"Confidence threshold ({config.confidence_threshold}) reached: {avg_confidence:.2f}"

    # Condition 3: Convergence (findings have stabilized)
    if previous_findings and round_number > 1:
        convergence = calculate_convergence(previous_findings, findings)

        if convergence >= config.convergence_threshold:
            return True, f"Convergence threshold ({config.convergence_threshold}) reached: {convergence:.2f}"

    # Condition 4: No new findings (all findings identical to previous round)
    if previous_findings and round_number > 1:
        # Check if root cause assessments are identical
        prev_rcs = {f.alert_id: f.root_cause_assessment for f in previous_findings}
        curr_rcs = {f.alert_id: f.root_cause_assessment for f in findings}

        if prev_rcs == curr_rcs:
            return True, "No new findings - assessments unchanged"

    # Continue investigation
    return False, ""
