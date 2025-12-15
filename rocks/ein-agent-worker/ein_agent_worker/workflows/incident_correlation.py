"""
Incident correlation using a two-pass parallel multi-agent pattern.

Each agent workflow performs one pass of analysis and returns the result.
The orchestrator runs Pass 1 in parallel, collects results, then runs Pass 2
in parallel with the aggregated context from Pass 1.
"""

from typing import Any, Dict, List
import asyncio
import json
from dataclasses import dataclass

from temporalio import workflow
from temporalio.contrib import openai_agents
from agents import Agent, Runner

# Prompt for the first, independent RCA pass
PASS_1_RCA_PROMPT = """You are an RCA analyst. Your task is to perform a root cause analysis for the given alert.
You do not have context from other alerts. Do your best and explicitly note any limitations or dependencies.

**Your Primary Alert to Investigate:**
{primary_alert_summary}

---
## Investigation & Deliverable

### Step 1: Identify the Resource and Its Dependencies
1.  **Identify the specific resource instance**: Determine exactly which resource is failing.
2.  **CRITICAL - Discover infrastructure placement**: If this is a workload resource (pod, container, etc.), you MUST use available tools to discover where it's running (which node, host, cluster, etc.). This information is ESSENTIAL for identifying potential upstream failures.
3.  **Identify all resource dependencies**: List ALL infrastructure and application resources this instance depends on.

### Step 2: Check Dependency Health
4.  **Check the health of EACH dependency**: For every dependency you identified, verify its current state and health using available tools.
5.  **Document the findings**: Record the state of each dependency.

### Step 3: Determine Root Cause vs Symptom
6.  **Analyze the failure pattern**:
    - If the root cause is entirely within the failing resource itself (e.g., misconfigured spec, bad image, insufficient resources **requested by this specific resource**), mark `is_likely_symptom: false`.
    - If ANY dependency is unhealthy or failed, mark `is_likely_symptom: true` and document the specific dependency in `suspected_upstream_cause`.
    - Example: If a workload is not ready AND its host/node is down or degraded, the workload failure is a SYMPTOM of the host failure.
7.  **If you cannot fully determine the root cause** due to missing context, document this in `limitations`.

### Step 4: Produce Report
8.  **CRITICAL**: Return ONLY a single, valid JSON object for your report.

```json
{{
  "alert_name": "{alertname}",
  "affected_resource": "Specific resource identifier with type prefix",
  "infrastructure_placement": "For workloads, specify where it runs (e.g., which node/host)",
  "root_cause_summary": "Brief summary of the immediate cause for THIS specific resource instance",
  "root_cause_details": "Detailed analysis including: 1) resource placement, 2) dependency health checks, 3) causal reasoning",
  "is_likely_symptom": false,
  "suspected_upstream_cause": "null OR specific upstream resource that failed",
  "limitations": "null or description of missing context needed for definitive RCA"
}}
```
"""

# Prompt for the second, corrective RCA pass, triggered by a signal
PASS_2_RCA_PROMPT = """You are a senior analyst who has just received new intelligence from your team.
Your task is to review your own initial findings in light of this new context and produce a final, definitive RCA report.

**Your Initial Draft Report:**
```json
{draft_rca}
```

**New Intelligence (Context from all other agents):**
{all_other_draft_rcas}

---
## Your Task
1.  **Analyze the New Context:** Review all other agents' reports to identify potential causal relationships **specific to your resource instance**.
2.  **Check for Resource-Specific Dependencies:**
    - Compare the `affected_resource` and `infrastructure_placement` from your draft with resources mentioned in other reports.
    - Only consider a dependency if there's a **direct relationship** between your specific resource and the failing resource in another report.
    - **CRITICAL**: Check if your `infrastructure_placement` matches any `affected_resource` in other reports - this indicates a direct dependency.
    - **Do NOT assume correlation based on alert name alone** - alerts with the same name may have completely different root causes if they affect different resource instances.
3.  **Identify Causal Dependencies (if they exist):**
    - Does your specific resource instance appear to be a **symptom** of a failure reported by another agent? Check if:
      - Your `infrastructure_placement` matches another agent's `affected_resource` (e.g., your workload runs on a failed node)
      - Any dependency you identified in Pass 1 is confirmed as failed by another agent's report
    - Is there evidence that your failure **caused** another agent's alert for a different resource?
    - Look for **direct dependency relationships**, not just temporal correlation.
4.  **Re-evaluate Your Initial Assessment:**
    - If your draft identified this as an independent root cause, but another agent's report reveals a **directly related upstream failure** (e.g., the node where your workload runs is down), reclassify this as a symptom.
    - If your draft noted `suspected_upstream_cause`, check if any other agent's report confirms this suspicion **for your specific resource**.
    - If no other agent's report is relevant to your specific resource instance, maintain your independent root cause assessment.
5.  **Form a Final Conclusion:** Synthesize your draft with the new intelligence to produce a definitive, causally-accurate RCA.
6.  **Produce the FINAL Report:** Create the final report with explicit causal attribution.

---
## Deliverable Format
Provide the **final, corrected** RCA report in JSON format.
**CRITICAL**: Return ONLY valid JSON.

```json
{{
  "alert_name": "{alertname}",
  "affected_resource": "Same specific resource identifier from draft",
  "infrastructure_placement": "Same infrastructure placement from draft",
  "is_symptom": false,
  "caused_by_alert": "null or the specific alert instance that caused this one (include affected_resource for clarity)",
  "caused_by_resource": "null or the specific resource that failed and caused this symptom (e.g., the node name)",
  "root_cause_summary": "Final summary with causal attribution if applicable",
  "root_cause_details": "Final details incorporating cross-agent context and explicit causal reasoning for THIS specific resource",
  "evidence": [],
  "affected_resources": [],
  "limitations": "null if fully resolved"
}}
```
"""

@workflow.defn
class InitialRcaWorkflow:
    """Performs the first-pass, independent RCA for a single alert."""

    @workflow.run
    async def run(self, alert: Dict[str, Any]) -> str:
        """Runs Pass 1: Independent RCA and returns the result."""
        workflow.logger.info(f"Starting Pass 1 RCA for {alert.get('alertname', 'unknown')}")

        prompt = PASS_1_RCA_PROMPT.format(
            primary_alert_summary=_format_alert_summary(alert),
            alertname=alert.get("alertname", "unknown")
        )

        mcp_servers = _load_mcp_servers()
        agent = Agent(
            name="InitialRCAAnalyst",
            instructions="You are an RCA analyst.",
            model="gemini/gemini-2.0-flash-exp",
            mcp_servers=mcp_servers,
        )

        result = await Runner.run(agent, input=prompt)
        workflow.logger.info(f"Completed Pass 1 RCA for {alert.get('alertname', 'unknown')}")
        return result.final_output


@workflow.defn
class CorrectiveRcaWorkflow:
    """Performs the second-pass, corrective RCA with context from other agents."""

    @workflow.run
    async def run(self, alert: Dict[str, Any], draft_rca: str, all_other_draft_rcas: str) -> str:
        """Runs Pass 2: Corrective RCA with context and returns the final result."""
        alertname = alert.get("alertname", "unknown")
        workflow.logger.info(f"Starting Pass 2 RCA for {alertname}")

        prompt = PASS_2_RCA_PROMPT.format(
            draft_rca=draft_rca,
            all_other_draft_rcas=all_other_draft_rcas,
            alertname=alertname,
        )

        mcp_servers = _load_mcp_servers()
        agent = Agent(
            name="CorrectiveRCAAnalyst",
            instructions="You are an RCA analyst.",
            model="gemini/gemini-2.0-flash-exp",
            mcp_servers=mcp_servers,
        )

        result = await Runner.run(agent, input=prompt)
        workflow.logger.info(f"Completed Pass 2 RCA for {alertname}")
        return result.final_output


def _load_mcp_servers() -> List[Any]:
    """Load MCP servers from workflow memo."""
    mcp_servers = []
    for name in workflow.memo_value("mcp_servers", default=[]):
        try:
            mcp_servers.append(openai_agents.workflow.stateless_mcp_server(name))
        except Exception as e:
            workflow.logger.warning(f"Failed to load MCP server '{name}': {e}")
    return mcp_servers

@workflow.defn
class IncidentCorrelationWorkflow:
    """Orchestrates two-pass parallel RCA agents for incident correlation."""

    @workflow.run
    async def run(self, alerts: List[Dict[str, Any]]) -> str:
        alert_count = len(alerts)
        workflow.logger.info(f"Orchestrating {alert_count} RCA agents in two passes.")

        # --- Pass 1: Run all initial RCA workflows in parallel ---
        workflow.logger.info("Starting Pass 1: Independent RCA for all alerts...")
        pass1_workflows = []
        for i, alert in enumerate(alerts):
            workflow_id = f"{workflow.info().workflow_id}-pass1-{i}"
            pass1_workflows.append(
                workflow.execute_child_workflow(
                    InitialRcaWorkflow.run,
                    args=[alert],
                    id=workflow_id,
                    task_queue=workflow.info().task_queue,
                    memo={"mcp_servers": workflow.memo_value("mcp_servers", default=[])},
                )
            )

        # Wait for all Pass 1 workflows to complete
        draft_rcas: List[str] = await asyncio.gather(*pass1_workflows)
        workflow.logger.info(f"Pass 1 complete. Collected {len(draft_rcas)} initial RCA reports.")

        # --- Pass 2: Run all corrective RCA workflows in parallel with context ---
        workflow.logger.info("Starting Pass 2: Corrective RCA with cross-agent context...")
        pass2_workflows = []
        for i, alert in enumerate(alerts):
            # Prepare context: all other draft RCAs (excluding this agent's own draft)
            other_drafts = [rca for j, rca in enumerate(draft_rcas) if i != j]
            all_other_context = "\n---\n".join(other_drafts)

            workflow_id = f"{workflow.info().workflow_id}-pass2-{i}"
            pass2_workflows.append(
                workflow.execute_child_workflow(
                    CorrectiveRcaWorkflow.run,
                    args=[alert, draft_rcas[i], all_other_context],
                    id=workflow_id,
                    task_queue=workflow.info().task_queue,
                    memo={"mcp_servers": workflow.memo_value("mcp_servers", default=[])},
                )
            )

        # Wait for all Pass 2 workflows to complete
        final_rcas: List[str] = await asyncio.gather(*pass2_workflows)
        workflow.logger.info(f"Pass 2 complete. Collected {len(final_rcas)} final RCA reports.")

        # --- Final Correlation ---
        return await self._run_final_correlation(final_rcas, alert_count)

    async def _run_final_correlation(self, final_rcas: List[str], alert_count: int) -> str:
        """Runs the final correlation step on the corrected RCAs."""
        workflow.logger.info("--- Starting Final Correlation ---")
        # Format the final reports for the prompt
        final_rca_reports = []
        for i, rca_str in enumerate(final_rcas):
            try:
                rca_json = json.loads(rca_str)
                final_rca_reports.append(f"RCA Report {i+1}:\n{json.dumps(rca_json, indent=2)}")
            except (json.JSONDecodeError, TypeError):
                final_rca_reports.append(f"RCA Report {i+1} (Raw):\n{rca_str}")
        
        mcp_servers = _load_mcp_servers()
        correlation_agent = Agent(
            name="FinalCorrelationAnalyst",
            instructions="You are a lead SRE creating the final incident report from a set of cross-validated RCAs.",
            model="gemini/gemini-2.5-pro",
            mcp_servers=mcp_servers,
        )
        # For simplicity, reusing a prompt template fragment. A dedicated one would be cleaner.
        result = await Runner.run(correlation_agent, input=CORRELATION_PROMPT_TEMPLATE.format(
            final_rca_reports="\n\n".join(final_rca_reports),
            alert_count=alert_count
        ))
        return result.final_output

# Util for formatting a single alert summary
def _format_alert_summary(alert: Dict[str, Any]) -> str:
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    summary_lines = [
        f"- **Alert:** {alert.get('alertname', 'N/A')}",
        f"- **Status:** {alert.get('status', 'N/A')}",
        f"- **Severity:** {labels.get('severity', 'N/A')}",
        f"- **Starts At:** {alert.get('starts_at', 'N/A')}",
    ]
    resource_keys = ["node", "namespace", "pod", "deployment", "statefulset", "daemonset", "job"]
    for key in resource_keys:
        if labels.get(key):
            summary_lines.append(f"- **{key.capitalize()}:** {labels[key]}")
    if annotations.get('summary'):
        summary_lines.append(f"- **Summary:** {annotations['summary']}")
    return "\n".join(summary_lines)

# Final Correlation Prompt (for reuse in final step)
CORRELATION_PROMPT_TEMPLATE = """You are a lead SRE creating the final incident report. You have received a set of high-quality, cross-validated RCA reports from your team. Your task is to group them into incidents based on causal relationships.

**Final RCA Reports:**
{final_rca_reports}

---
## Your Task
1.  **Examine Each Alert Individually:** Review the `affected_resource`, `infrastructure_placement`, `is_symptom`, `caused_by_alert`, and `caused_by_resource` fields for each report.
2.  **Identify Causal Chains:**
    - Look for alerts where `is_symptom: true` and `caused_by_alert`/`caused_by_resource` is set. These form causal dependency chains.
    - Verify the causal relationship by checking if the symptom's `infrastructure_placement` matches the root cause's `affected_resource`.
    - Example: If Alert B (pod) has `infrastructure_placement: "node/X"` and Alert A (node) has `affected_resource: "node/X"`, then B is a symptom of A.
3.  **Group into Incidents:**
    - **Rule 1**: If Alert B is caused by Alert A (according to `caused_by_alert` or infrastructure matching), they belong to the same incident with A as primary and B as secondary.
    - **Rule 2**: Alerts with `is_symptom: false` and no `caused_by_alert` are independent root causes and should each be a separate incident.
    - **Rule 3**: DO NOT group alerts together just because they have the same alert name - each alert instance may have a completely different root cause affecting different resources.
    - **Rule 4**: Only group alerts if there's an explicit causal relationship documented in the `caused_by_alert`/`caused_by_resource` fields or confirmed by infrastructure placement matching.
4.  **Designate Primary Alerts:** The primary alert should be the root cause (where `is_symptom: false`), not the symptom. Symptom alerts should be secondary.
5.  **Articulate Causal Relationships:**
    - For incidents with causal chains, use the `causal_chain` field to explicitly describe how the primary alert caused the secondary alerts, referencing specific resource identifiers and the infrastructure dependency.
    - For independent incidents, set `causal_chain: "Independent failure"`.

## Deliverable Format
**CRITICAL**: Return ONLY valid JSON.

{{
  "total_alerts": {alert_count},
  "total_incidents": <Number of distinct incidents - one per independent root cause>,
  "incidents": [
    {{
      "incident_id": 1,
      "primary_alert": "The root cause alert (is_symptom: false)",
      "secondary_alerts": ["Alerts where caused_by_alert references the primary alert"],
      "causal_chain": "Explicit description with resource identifiers, or 'Independent failure'",
      "common_root_cause_category": "...",
      "common_root_cause": "Root cause for THIS incident, not a generic summary",
      "shared_resources": ["Resources involved in THIS incident only"],
      "temporal_relationship": "...",
      "incident_severity": "...",
      "affected_services": [],
      "recommended_actions": ["Actions specific to THIS incident"]
    }}
  ]
}}
"""
