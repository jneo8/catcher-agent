# KubePodNotReady Alert - Root Cause Analysis Specification

## Overview

This document provides a specification for AI-driven root cause analysis (RCA) of the `KubePodNotReady` Prometheus alert.

### Alert Definition

**Alert Name**: `KubePodNotReady`

**Trigger Condition**:
```promql
sum by (namespace, pod, cluster) (
  max by(namespace, pod, cluster) (
    kube_pod_status_phase{job="kube-state-metrics", phase=~"Pending|Unknown|Failed"}
  ) * on(namespace, pod, cluster) group_left(owner_kind) topk by(namespace, pod, cluster) (
    1, max by(namespace, pod, owner_kind, cluster) (kube_pod_owner{owner_kind!="Job"})
  )
) > 0
```

**Duration**: 15 minutes

**Severity**: Warning

**Description**: Pod has been in a non-ready state (Pending, Unknown, or Failed phase) for longer than 15 minutes.

---

## Possible Root Causes

The AI agent should investigate and determine which of the following three primary root causes is responsible:

### 1. Insufficient Resources (Pod in Pending Phase)
- **Symptoms**: Pod cannot be scheduled to any node
- **Common Reasons**:
  - Insufficient CPU resources across all nodes
  - Insufficient memory resources across all nodes
  - Node at maximum pod capacity
  - No nodes match pod's node selector or affinity rules
  - All nodes are tainted and pod doesn't have matching tolerations

### 2. Image Pull Failures (Pod in Pending Phase)
- **Symptoms**: Pod scheduled but containers cannot start
- **Common Reasons**:
  - Image does not exist or incorrect image name/tag
  - Private registry authentication failure (missing/invalid imagePullSecrets)
  - Network connectivity issues to container registry
  - Registry rate limiting (e.g., Docker Hub)
  - Image too large or disk space issues

### 3. Container Failure (Pod in Failed Phase)
- **Symptoms**: Container started but exited with error
- **Common Reasons**:
  - Application crash or unhandled exception
  - Missing configuration or environment variables
  - Failed health checks (startup/liveness probes)
  - Insufficient permissions or missing dependencies
  - Out of memory (OOMKilled)

---

## Available MCP Tools

1. Kubernetes MCP Server: https://github.com/containers/kubernetes-mcp-server

2. Grafana MCP Server: https://github.com/grafana/mcp-grafana

---

## AI Agent Prompt Template

Use this template to guide the AI agent in investigating KubePodNotReady alerts:

```
ALERT: KubePodNotReady
Pod: <pod-name>
Namespace: <namespace>
Cluster: <cluster-name>
Duration: Pod has been in non-ready state for 15+ minutes

Your task is to perform root cause analysis for this alert using the available MCP tools.

Follow this investigation workflow:

PHASE 1: Initial Assessment
1. Get the pod details and identify its current phase (Pending/Unknown/Failed)
2. Check pod events for any obvious error messages
3. Identify if the pod is part of a Deployment, StatefulSet, or DaemonSet

PHASE 2: Root Cause Investigation

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
Provide a clear root cause analysis with:
1. Root cause category: Resource Shortage / Image Pull Failure / Container Failure
2. Specific root cause (e.g., "Insufficient CPU resources", "Invalid imagePullSecret", "Application crash")
3. Evidence from logs, events, or metrics
4. Recommended remediation action
5. Any related alerts that are also firing
```

---

## Reproducing Test Scenarios

### SCENARIO A, B & C: Combined Test

This manifest reproduces all three scenarios: SCENARIO A (pod not scheduled), SCENARIO B (image pull failure), and SCENARIO C (container failure).

#### Steps to Reproduce

Create a YAML file with all test pods:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-insufficient-cpu
  namespace: failure-cases
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: test-node
            operator: In
            values:
            - "true"
          - key: failure-node
            operator: NotIn
            values:
            - "true"
  containers:
  - name: app
    image: nginx:latest
    resources:
      requests:
        cpu: "1000"  # Request 1000 CPU cores (unrealistic) - SCENARIO A
        memory: "128Mi"
---
apiVersion: v1
kind: Pod
metadata:
  name: test-image-pull-failure
  namespace: failure-cases
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: test-node
            operator: In
            values:
            - "true"
          - key: failure-node
            operator: NotIn
            values:
            - "true"
  containers:
  - name: app
    image: nonexistent-registry.io/nonexistent-image:latest  # SCENARIO B
---
apiVersion: v1
kind: Pod
metadata:
  name: test-container-failure
  namespace: failure-cases
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: test-node
            operator: In
            values:
            - "true"
          - key: failure-node
            operator: NotIn
            values:
            - "true"
  restartPolicy: Never  # Pod will enter Failed phase when container exits
  containers:
  - name: app
    image: busybox:latest
    command: ["/bin/sh", "-c", "echo 'Application starting...'; sleep 5; echo 'Application crashed!'; exit 1"]
    # SCENARIO C: Container exits with error code, pod enters Failed phase
```

Apply the manifest:
```bash
kubectl apply -f test-scenarios.yaml
```

**Expected Results**:
- **SCENARIO A**: `test-insufficient-cpu` remains in Pending phase with `FailedScheduling` event showing "Insufficient cpu"
- **SCENARIO B**: `test-image-pull-failure` is scheduled but remains in Pending phase with `ImagePullBackOff` or `ErrImagePull`
- **SCENARIO C**: `test-container-failure` starts, container exits with error code 1, pod enters Failed phase

#### Verification

1. Check all pods:
   ```bash
   kubectl get pods -n failure-cases -o wide
   ```

2. Check detailed status:
   ```bash
   kubectl describe pod test-insufficient-cpu -n failure-cases
   kubectl describe pod test-image-pull-failure -n failure-cases
   kubectl describe pod test-container-failure -n failure-cases
   ```

3. For SCENARIO C, check container logs:
   ```bash
   kubectl logs test-container-failure -n failure-cases
   ```

4. Wait 15+ minutes for the `KubePodNotReady` alerts to fire for all pods.

#### Cleanup

```bash
kubectl delete pod test-insufficient-cpu test-image-pull-failure test-container-failure -n failure-cases
```

---

## References

- Alert Rule Definition: https://raw.githubusercontent.com/prometheus-operator/kube-prometheus/v0.15.0/manifests/kubernetesControlPlane-prometheusRule.yaml
- Kubernetes MCP: https://github.com/containers/kubernetes-mcp-server
- Grafana MCP: https://github.com/grafana/mcp-grafana
