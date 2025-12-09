from temporallib.client import Client, Options
import asyncio

async def main():
    client_opt = Options(
        host="localhost:7233",
        queue="ein-agent-queue",
        namespace="default",
    )

    client = await Client.connect(client_opt=client_opt)
    workflow_name = "SingleAlertInvestigationWorkflow"
    workflow_id = "single-alert-investigation-id"

    enabled_server_names = ["kubernetes", "grafana"]

    prompt = """ALERT: KubePodNotReady1M

Your task is to perform root cause analysis for all firing KubePodNotReady1M alerts using the available MCP tools.

Follow this investigation workflow:

PHASE 0: Alert Discovery
1. Query Prometheus to find all currently firing KubePodNotReady1M alerts:
   - Use query: ALERTS{alertname="KubePodNotReady1M"}
   - Extract pod name, namespace, and cluster from the alert labels
   - List all affected pods

PHASE 1: Initial Assessment (for each affected pod)
1. Get the pod details and identify its current phase (Pending/Unknown/Failed)
2. Check pod events for any obvious error messages
3. Identify if the pod is part of a Deployment, StatefulSet, or DaemonSet

PHASE 2: Root Cause Investigation (for each affected pod)

Based on the pod phase, investigate ONE of these scenarios:

SCENARIO A: If pod is in "Pending" phase and NOT scheduled
- Check for FailedScheduling events
- Examine resource requests vs. node capacity
- Check node selectors, affinity rules, taints, and tolerations
- Query Prometheus for cluster resource utilization
- Look for related alerts: KubeCPUOvercommit, KubeMemoryOvercommit

SCENARIO B: If pod is in "Pending" phase and IS scheduled
- Check container statuses for ImagePullBackOff or ErrImagePull
- Verify image name and tag
- Check imagePullSecrets configuration
- Query containerd logs for image pull failures
- Look for authentication, network, or rate limiting errors

SCENARIO C: If pod is in "Failed" phase
- Check container exit code and termination reason
- Review container logs for error messages or stack traces
- Check if container was OOMKilled (out of memory)
- Examine pod events for BackOff, CrashLoopBackOff, or Error events
- Verify resource limits vs. actual usage
- Check for failed liveness/startup probes

IMPORTANT NOTES:
- This is Canonical Kubernetes - logs must be queried from Loki
- Available Canonical Kubernetes services: k8s.kubelet, k8s.containerd
- Use query format: {instance="<node-name>"} |= `snap.k8s.<service>.service`
- Consider time ranges - the incident may not be happening in real-time
- Perform READ-ONLY operations only
- Provide evidence for your conclusion with specific log entries or metric values

DELIVERABLE:
For each affected pod, provide a clear root cause analysis with:
1. Pod name, namespace, and cluster
2. Root cause category: Resource Shortage / Image Pull Failure / Container Failure
3. Specific root cause (e.g., "Insufficient CPU resources", "Invalid imagePullSecret", "Application crash")
4. Evidence from logs, events, or metrics
5. Recommended remediation action
6. Any related alerts that are also firing

Provide a summary at the end with the total number of affected pods and common patterns if any.
"""

    await client.execute_workflow(
        workflow_name,
        # prompt,
        "please tell me a joke",
        id=workflow_id,
        task_queue="ein-agent-queue",
        memo={"mcp_servers": enabled_server_names},
    )


if __name__ == "__main__":
    asyncio.run(main())
