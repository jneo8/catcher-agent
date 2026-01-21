# Ceph OSD Failure Scenario

This document describes how to reproduce a Ceph OSD failure that propagates to Kubernetes workloads.

## Overview

Simulate disk/OSD failure by stopping OSD services. This causes Ceph to lose quorum, making storage unavailable and causing Kubernetes pods to fail.

## Prerequisites

```bash
# Verify MicroCeph is running
microceph status

# Check storage class name
kubectl get storageclass | grep ceph
```

## Reproduce the Failure

### Step 1: Check Ceph Configuration

```bash
# Check number of OSDs
microceph disk list
sudo ceph osd tree

# Check pool replication settings
sudo ceph osd pool ls
# Common pool names: xfs-pool, ext4-pool, ceph-kubernetes
sudo ceph osd pool get xfs-pool size      # Returns replica count (usually 3)
sudo ceph osd pool get xfs-pool min_size  # Minimum replicas needed (usually 2)
```

**Key Info:**
- If `size=3` and `min_size=2`: Need to stop **2 or more OSDs** to cause failure
- If `size=2` and `min_size=1`: Need to stop **2 OSDs** to cause failure

### Step 2: Stop OSDs

```bash
# Check running OSD processes
ps aux | grep ceph-osd | grep -v grep

# Stop multiple OSDs using ceph command (adjust IDs based on your setup)
# To cause failure with size=3, min_size=2, stop 2 OSDs
sudo ceph osd stop 1 2

# Verify Ceph enters error state
sudo ceph health detail
# Expected: HEALTH_WARN or HEALTH_ERR

sudo ceph status
# Expected: Shows OSDs down, PGs in degraded/inactive state
```

### Step 3: Deploy Test Workload

```bash
# Apply the test deployment
kubectl apply -f ceph-failure-test-deployment.yaml
```

**Note:** The deployment uses `ceph-xfs` storage class. If your cluster uses a different storage class name, update the `storageClassName` field in the YAML file.

### Step 4: Observe the Failure

```bash
# Watch PVC status (should stay Pending)
kubectl get pvc ceph-failure-test-pvc -w

# Check PVC events
kubectl describe pvc ceph-failure-test-pvc

# Watch pod status (should stay ContainerCreating or Pending)
kubectl get pods -l app=ceph-failure-test -w

# Check pod events
kubectl describe pod -l app=ceph-failure-test
```

## Expected Results

**Ceph Level:**
- Health: `HEALTH_ERR` or `HEALTH_WARN`
- Messages: "X OSDs down", "Reduced data availability", "PGs stuck inactive"

**Kubernetes Level:**
- PVC Status: `Pending` (never becomes `Bound`)
- Pod Status: `Pending` or `ContainerCreating`
- Pod Events: `FailedScheduling` or `FailedMount`

**Expected Alerts:**
- `CephOSDDown`
- `CephClusterCritical`
- `PersistentVolumeClaimPending`
- `PodStuckInPending`
- `DeploymentReplicasNotReady`

## Recovery

```bash
# Restart the OSD service (this will restart all stopped OSDs)
sudo systemctl restart snap.microceph.osd.service

# Or manually start individual OSDs if needed
# The OSDs should auto-restart, but you can verify with:
ps aux | grep ceph-osd | grep -v grep

# Watch Ceph recovery
sudo ceph -w
# Wait for: HEALTH_OK (may take 30-60 seconds)

# Verify OSD status
sudo ceph osd tree
# All OSDs should show "up"

# Verify PVC and pod recover
kubectl get pvc ceph-failure-test-pvc
kubectl get pods -l app=ceph-failure-test

# Cleanup
kubectl delete deployment ceph-failure-test
kubectl delete pvc ceph-failure-test-pvc
```

## Quick Reference

```bash
# Check Ceph health
sudo ceph status
sudo ceph health detail

# Check OSD status and processes
sudo ceph osd tree
sudo ceph osd stat
ps aux | grep ceph-osd | grep -v grep

# Check Kubernetes resources
kubectl get pvc -A
kubectl get pods -A | grep -v Running
kubectl get events --sort-by='.lastTimestamp' | grep -i ceph
```
