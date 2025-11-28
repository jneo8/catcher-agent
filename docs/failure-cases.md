## Statefulset stuck on scheduling

### Deploy enviroment

```sh
$ kubectl get node
NAME            STATUS   ROLES                  AGE   VERSION
juju-bf3765-0   Ready    control-plane,worker   19h   v1.32.9
juju-bf3765-4   Ready    worker                 19h   v1.32.9
juju-bf3765-5   Ready    worker                 19h   v1.32.9
juju-bf3765-6   Ready    worker                 18h   v1.32.9
juju-bf3765-7   Ready    worker                 78m   v1.32.9
juju-bf3765-8   Ready    worker                 77m   v1.32.9

$ kubectl label node juju-bf3765-6 test-node=true
$ kubectl label node juju-bf3765-7 test-node=true
$ kubectl label node juju-bf3765-8 test-node=true

$ juju add-model reproduce-failure
$ juju set-model-constraints "tags=node.test-node=true"
$ juju deploy minio -n 3
```

## Initial deployment status

```sh
# Get k8s pods
$ kubectl get pod -n reproduce-failure -o wide
NAME                             READY   STATUS    RESTARTS   AGE     IP           NODE            NOMINATED NODE   READINESS GATES
minio-0                          1/1     Running   0          66s     10.1.4.239   juju-bf3765-6   <none>           <none>
minio-1                          1/1     Running   0          66s     10.1.5.78    juju-bf3765-8   <none>           <none>
minio-2                          1/1     Running   0          66s     10.1.1.57    juju-bf3765-7   <none>           <none>
minio-operator-0                 1/1     Running   0          106s    10.1.5.19    juju-bf3765-8   <none>           <none>
modeloperator-7c48d674d5-c6h6s   1/1     Running   0          4m18s   10.1.1.120   juju-bf3765-7   <none>           <none>

# The app is deployed by juju
$ juju status
Model              Controller    Cloud/Region  Version  SLA          Timestamp
reproduce-failure  lxd-k8s-ctrl  lxdk8scloud   3.6.12   unsupported  11:26:55+08:00

App    Version                Status   Scale  Charm  Channel          Rev  Address         Exposed  Message
minio  res:oci-image@7f2474f  waiting      3  minio  ckf-1.10/stable  583  10.152.183.140  no       Waiting for leadership

Unit      Workload  Agent  Address     Ports          Message
minio/0*  active    idle   10.1.4.239  9000-9001/TCP  
minio/1   waiting   idle   10.1.5.78   9000-9001/TCP  Waiting for leadership
minio/2   waiting   idle   10.1.1.57   9000-9001/TCP  Waiting for leadership

# The service available on the k8s worker node
# test-k8s-worker/0 is the juju-bf3765-6.
$ juju exec --unit test-k8s-worker/0 -- snap services
Service                      Startup   Current   Notes
k8s.containerd               enabled   active    -
k8s.etcd                     disabled  inactive  -
k8s.k8s-apiserver-proxy      enabled   active    -
k8s.k8s-dqlite               disabled  inactive  -
k8s.k8sd                     enabled   active    -
k8s.kube-apiserver           disabled  inactive  -
k8s.kube-controller-manager  disabled  inactive  -
k8s.kube-proxy               enabled   active    -
k8s.kube-scheduler           disabled  inactive  -
k8s.kubelet                  enabled   active    -
```

## Reproduce the Failure

1. **Stop kubelet on the node hosting minio-0, which is juju-bf3765-6**

```sh
# Stop the kubelet service where pod minio-1 live.
$ juju exec --unit test-k8s-worker/0 -- sudo snap stop k8s.kubelet

#  Wait for node to become NotReady** (~40 seconds)
$ kubectl get node
NAME            STATUS     ROLES                  AGE   VERSION
juju-bf3765-0   Ready      control-plane,worker   20h   v1.32.9
juju-bf3765-4   Ready      worker                 19h   v1.32.9
juju-bf3765-5   Ready      worker                 19h   v1.32.9
juju-bf3765-6   NotReady   worker                 19h   v1.32.9
juju-bf3765-7   Ready      worker                 85m   v1.32.9
juju-bf3765-8   Ready      worker                 84m   v1.32.9

```

2. **Attempt to scale down the StatefulSet**

```sh
# schedule minio to 0 unit
$ juju scale-application minio 0
# minio-0 will remain in "Terminating" state
$ kubectl get pod -n reproduce-failure
NAME                             READY   STATUS        RESTARTS   AGE
minio-0                          1/1     Terminating   0          5m39s
minio-operator-0                 1/1     Running       0          6m19s
modeloperator-7c48d674d5-c6h6s   1/1     Running       0          8m51s

```

3. **Re-schedule unit to 5**

```sh
$ juju scale-application minio 5

$ kubectl get pod -n reproduce-failure
NAME                             READY   STATUS        RESTARTS   AGE
minio-0                          1/1     Terminating   0          8m52s
minio-1                          1/1     Running       0          17s
minio-2                          1/1     Running       0          87s
minio-3                          1/1     Running       0          98s
minio-4                          1/1     Running       0          112s
minio-operator-0                 1/1     Running       0          9m32s
modeloperator-7c48d674d5-c6h6s   1/1     Running       0          12m

# The Sclae number will stuck at 4 because the pod minio-0 is stuck in Terminating
$ juju status -m reproduce-failure
Model              Controller    Cloud/Region  Version  SLA          Timestamp
reproduce-failure  lxd-k8s-ctrl  lxdk8scloud   3.6.12   unsupported  11:35:03+08:00

App    Version                Status   Scale  Charm  Channel          Rev  Address         Exposed  Message
minio  res:oci-image@7f2474f  waiting    4/5  minio  ckf-1.10/stable  583  10.152.183.140  no       Waiting for leadership

Unit      Workload  Agent  Address     Ports          Message
minio/3*  active    idle   10.1.5.59   9000-9001/TCP  
minio/4   waiting   idle   10.1.1.145  9000-9001/TCP  Waiting for leadership
minio/5   waiting   idle   10.1.1.93   9000-9001/TCP  Waiting for leadership
minio/6   waiting   idle   10.1.5.115  9000-9001/TCP  Waiting for leadership
```

## Trouble shooting with agent

### Available MCP servers

- https://github.com/containers/kubernetes-mcp-server
- https://github.com/grafana/mcp-grafana

prompt:

```
The pod minio-0 in namespace reproduce-failure is stuck in Terminating, can you troubleshoot for me? Please only do read-only checking.

Please follow these steps:
1. Check the status of the pod using kubernetes tools
2. Check the logs of all the kubernetes component if needed

Important notes about logs:
- The kubernetes component logs CANNOT be reached by the mcp-k8s tools because this is Canonical Kubernetes
- Service logs are in snap service logs and should be queried from Loki

## How to query the canonical kubernets service logs

The available canonical kubernetes services are:
- k8s.kubelet
- k8s.containerd

For example, to check kubelet logs, query Loki with:

```
{instance="{instance_name}"} |= `snap.k8s.kubelet.service`
```

Note: The incident can happen not in real time, so the logs query should consider the time.
Note: Please also verify the service status
```

result:

```
The `minio-0` pod is stuck in a terminating state because its node, `juju-bf3765-6`, is unhealthy.

The kubelet on this node has stopped reporting its status, causing the control plane to mark it as unreachable and taint it with `NoExecute`.
The taint manager then began evicting the pod. Since the kubelet is unresponsive, the pod's termination process cannot complete.
I was unable to retrieve logs, which further indicates a problem with the node."
```
