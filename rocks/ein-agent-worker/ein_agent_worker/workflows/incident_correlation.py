"""Incident correlation workflow that spawns child investigations and merges results."""

from typing import Any, Dict, List

from temporalio import workflow
from temporalio.contrib import openai_agents
from agents import Agent, Runner


# Child investigation prompt template
CHILD_INVESTIGATION_PROMPT = """ALERT: {alertname}
Status: {status}
Severity: {severity}
Cluster: {cluster}
Started At: {starts_at}
{ended_at_line}

## Alert Context
{context_lines}

## Alert Details
{details_lines}

---

Your task is to perform comprehensive root cause analysis for this alert using the available MCP tools (Kubernetes, Grafana).

## Environment-Specific Information

**Canonical Kubernetes Log Access**:
- This cluster runs Canonical Kubernetes - system logs are in Loki, NOT accessible via kubectl logs for system components
- Available system services: `k8s.kubelet`, `k8s.containerd`, `k8s.kube-apiserver`, `k8s.kube-scheduler`, `k8s.kube-controller-manager`
- Loki query format: `{{instance="<node-name>"}} |= "snap.k8s.<service>.service"`
- Application pod logs: Use standard kubectl/Kubernetes API
- Always use appropriate time ranges based on alert start time: {starts_at}

## Investigation Approach

1. Verify current state using available tools (Kubernetes resources, Prometheus metrics, logs)
2. Gather evidence from multiple sources (events, metrics, logs)
3. Identify the root cause with supporting evidence (timestamps, metric values, log excerpts)
4. Determine impact and provide actionable recommendations

## Important Guidelines

- **READ-ONLY Operations**: Perform only read operations; do not modify any resources
- **Evidence-Based Analysis**: Support all conclusions with specific log entries, metric values, or resource states
- **Time Awareness**: This alert may not be happening in real-time; use appropriate time ranges
- **Comprehensive Coverage**: Look for all contributing factors

## Deliverable Format

Provide a structured root cause analysis report in JSON format:

{{
  "alert_name": "{alertname}",
  "root_cause_category": "Resource Issue|Configuration Error|Application Failure|Infrastructure Problem|Scheduling Issue|Storage Issue|Network Issue|Security/Certificate Issue",
  "root_cause_summary": "Brief 1-sentence summary of root cause",
  "root_cause_details": "Detailed explanation with evidence",
  "evidence": [
    "Specific log entry with timestamp",
    "Metric value: metric_name=X at time T",
    "Resource state: resource description"
  ],
  "affected_resources": [
    "namespace/pod/node names"
  ],
  "impact_severity": "Critical|High|Medium|Low",
  "impact_description": "What is affected and how",
  "immediate_actions": [
    "Action 1",
    "Action 2"
  ],
  "preventive_measures": [
    "Measure 1",
    "Measure 2"
  ],
  "limitations": "Any limitations in the investigation"
}}

**CRITICAL**: Return ONLY valid JSON, no additional text before or after the JSON object.
"""


# Correlation agent instructions
CORRELATION_AGENT_INSTRUCTIONS = """You are an incident correlation analyst. Your role is to analyze multiple RCA results and identify incident boundaries.

Your task:
1. Determine if multiple alerts represent one incident or multiple independent incidents
2. Identify primary vs secondary alerts (root cause vs symptoms)
3. Find common patterns and shared resources
4. Provide a structured incident analysis

Be precise and evidence-based. Use the RCA evidence provided to support your conclusions."""


# RCA result formatting template for correlation
RCA_RESULT_FORMAT = """
═══════════════════════════════════════════════════════════════
RCA {rca_index}: {alert_name}
═══════════════════════════════════════════════════════════════
Alert Status: {alert_status}
Started At: {starts_at}
Severity: {severity}

RCA Result:
{rca_result}
"""


# Parent correlation prompt template
CORRELATION_PROMPT_TEMPLATE = """You received {alert_count} alerts from the monitoring system within the same time window.

Each alert has been investigated independently. Below are the RCA results:

{rca_results}

---

Your task is to analyze these independent RCA results and determine incident boundaries.

## Incident Correlation Analysis

### Step 1: Identify Relationships Between Alerts
- Check if alerts share common resources (same node, namespace, deployment, pod, etc.)
- Examine timing patterns from the RCA results - did alerts fire simultaneously or in sequence?
- Look for parent-child or causal relationships mentioned in the RCA evidence
- Consider Kubernetes resource hierarchy: Cluster > Node > Namespace > Workload > Pod > Container

### Step 2: Determine Incident Count
Decide if these alerts represent:

**SINGLE INCIDENT** - All alerts are symptoms of one root cause:
- Example: Node failure causing multiple pod failures on that node
- Example: Deployment misconfiguration causing pod crashes and replica mismatches
- Indicators: Same root cause in RCAs, same resource (node/namespace), temporal correlation

**MULTIPLE INCIDENTS** - Independent issues happening simultaneously:
- Example: Node failure in one AZ + unrelated quota issue in different namespace
- Indicators: Different root causes, different resources, no causal relationship

### Step 3: Classify Each Incident
For each incident you identify:
- **Primary Alert**: Which alert represents the root cause (not a symptom)?
- **Secondary Alerts**: Which alerts are consequences/cascading effects?
- **Common Root Cause**: What is the underlying issue connecting them?

## Deliverable Format

Provide your analysis in JSON format:

{{
  "total_alerts": {alert_count},
  "total_incidents": 1,
  "incidents": [
    {{
      "incident_id": 1,
      "primary_alert": "alert name",
      "secondary_alerts": ["alert1", "alert2"],
      "common_root_cause_category": "category",
      "common_root_cause": "Explanation of shared root cause",
      "shared_resources": ["node-1", "namespace/default"],
      "temporal_relationship": "Alert X fired first at T0, then alerts Y and Z at T0+5s",
      "incident_severity": "Critical|High|Medium|Low",
      "affected_services": ["service names"],
      "recommended_actions": [
        "Action 1",
        "Action 2"
      ]
    }}
  ],
  "cross_incident_analysis": "If multiple incidents: any common factors? Otherwise: null"
}}

**CRITICAL**: Return ONLY valid JSON, no additional text before or after the JSON object.
"""


@workflow.defn
class IncidentCorrelationWorkflow:
    """Parent workflow that coordinates child alert investigations and correlates results."""

    @workflow.run
    async def run(self, alerts: List[Dict[str, Any]]) -> str:
        """
        Run incident correlation workflow.

        Args:
            alerts: List of alert dictionaries with fields:
                - alertname: str
                - status: str
                - labels: Dict[str, str]
                - annotations: Dict[str, str]
                - starts_at: str (ISO datetime)
                - ends_at: str (ISO datetime)
                - fingerprint: str
                - generator_url: str

        Returns:
            JSON string containing incident correlation analysis
        """
        workflow.logger.info(f"Starting incident correlation for {len(alerts)} alerts")

        # Get MCP servers from memo
        mcp_server_names = workflow.memo_value("mcp_servers", default=[])
        workflow.logger.info(f"MCP servers: {mcp_server_names}")

        # Spawn child workflow for each alert
        child_handles = []
        for idx, alert in enumerate(alerts):
            alert_name = alert.get("alertname", "unknown")

            # Create child investigation prompt
            child_prompt = self._create_child_prompt(alert)

            # Spawn child workflow
            workflow.logger.info(f"Spawning child workflow {idx+1}/{len(alerts)} for alert: {alert_name}")

            child_handle = await workflow.start_child_workflow(
                "SingleAlertInvestigationWorkflow",
                args=[child_prompt],
                id=f"{workflow.info().workflow_id}-child-{alert_name}-{alert.get('fingerprint', idx)}",
                task_queue=workflow.info().task_queue,
                memo={"mcp_servers": mcp_server_names},
            )
            child_handles.append({
                "handle": child_handle,
                "alert_name": alert_name,
                "alert": alert,
            })

        # Collect all child results
        workflow.logger.info(f"Waiting for {len(child_handles)} child workflows to complete")
        rca_results = []
        for idx, child_info in enumerate(child_handles):
            workflow.logger.info(f"Waiting for child {idx+1}/{len(child_handles)}: {child_info['alert_name']}")
            try:
                result = await child_info["handle"]
                rca_results.append({
                    "alert_name": child_info["alert_name"],
                    "alert": child_info["alert"],
                    "rca_result": result,
                })
                workflow.logger.info(f"Child {idx+1} completed: {child_info['alert_name']}")
            except Exception as e:
                workflow.logger.error(f"Child workflow failed for {child_info['alert_name']}: {e}")
                rca_results.append({
                    "alert_name": child_info["alert_name"],
                    "alert": child_info["alert"],
                    "rca_result": f"Investigation failed: {str(e)}",
                })

        # Run correlation agent
        workflow.logger.info("Running correlation analysis")
        correlation_prompt = self._create_correlation_prompt(rca_results)

        # Load MCP servers for correlation agent
        mcp_servers = []
        if mcp_server_names:
            for mcp_server_name in mcp_server_names:
                try:
                    server = openai_agents.workflow.stateless_mcp_server(mcp_server_name)
                    mcp_servers.append(server)
                    workflow.logger.info(f"Loaded MCP server for correlation: {mcp_server_name}")
                except Exception as e:
                    workflow.logger.warning(f"Failed to load MCP server '{mcp_server_name}': {e}")

        correlation_agent = Agent(
            name="CorrelationAnalyst",
            instructions=CORRELATION_AGENT_INSTRUCTIONS,
            model="gemini/gemini-2.5-flash",
            mcp_servers=mcp_servers,
        )

        correlation_result = await Runner.run(correlation_agent, input=correlation_prompt)

        workflow.logger.info("Incident correlation completed")
        return correlation_result.final_output

    def _create_child_prompt(self, alert: Dict[str, Any]) -> str:
        """Create investigation prompt for a single alert."""
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        # Build context lines
        context_lines = []
        if labels.get("namespace"):
            context_lines.append(f"  - Namespace: {labels['namespace']}")
        if labels.get("pod"):
            context_lines.append(f"  - Pod: {labels['pod']}")
        if labels.get("node"):
            context_lines.append(f"  - Node: {labels['node']}")
        if labels.get("deployment"):
            context_lines.append(f"  - Deployment: {labels['deployment']}")
        if labels.get("statefulset"):
            context_lines.append(f"  - StatefulSet: {labels['statefulset']}")
        if labels.get("daemonset"):
            context_lines.append(f"  - DaemonSet: {labels['daemonset']}")
        if labels.get("job"):
            context_lines.append(f"  - Job: {labels['job']}")
        if labels.get("persistentvolumeclaim"):
            context_lines.append(f"  - PVC: {labels['persistentvolumeclaim']}")

        # Build details lines
        details_lines = []
        if annotations.get("description"):
            details_lines.append(f"  - Description: {annotations['description']}")
        if annotations.get("summary"):
            details_lines.append(f"  - Summary: {annotations['summary']}")
        if annotations.get("runbook_url"):
            details_lines.append(f"  - Runbook: {annotations['runbook_url']}")

        # Build ended_at line
        ends_at = alert.get("ends_at", "")
        ended_at_line = ""
        if ends_at and ends_at != "0001-01-01T00:00:00Z":
            ended_at_line = f"Ended At: {ends_at}"

        return CHILD_INVESTIGATION_PROMPT.format(
            alertname=alert.get("alertname", "unknown"),
            status=alert.get("status", "unknown"),
            severity=labels.get("severity", "unknown"),
            cluster=labels.get("cluster", "unknown"),
            starts_at=alert.get("starts_at", "unknown"),
            ended_at_line=ended_at_line,
            context_lines="\n".join(context_lines) if context_lines else "  (no context available)",
            details_lines="\n".join(details_lines) if details_lines else "  (no details available)",
        )

    def _create_correlation_prompt(self, rca_results: List[Dict[str, Any]]) -> str:
        """Create correlation prompt from RCA results."""
        # Format RCA results for the prompt
        formatted_results = []
        for idx, result in enumerate(rca_results):
            alert = result["alert"]
            formatted_results.append(RCA_RESULT_FORMAT.format(
                rca_index=idx+1,
                alert_name=result['alert_name'],
                alert_status=alert.get('status'),
                starts_at=alert.get('starts_at'),
                severity=alert.get('labels', {}).get('severity', 'unknown'),
                rca_result=result['rca_result'],
            ))

        return CORRELATION_PROMPT_TEMPLATE.format(
            alert_count=len(rca_results),
            rca_results="\n".join(formatted_results),
        )
