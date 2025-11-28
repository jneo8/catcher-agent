from temporallib.client import Client, Options
import asyncio

async def main():
    client_opt = Options(
        host="localhost:7233",
        queue="catcher-agent-queue",
        namespace="default",
    )

    client = await Client.connect(client_opt=client_opt)
    workflow_name = "HelloWorkflow"
    workflow_id = "helloworld-id"

    enabled_server_names = ["kubernetes", "grafana"]

    prompt = """The pod minio-0 in namespace reproduce-failure is stuck in Terminating, can you troubleshoot for me? Please only do read-only checking.

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
"""

    await client.execute_workflow(
        workflow_name,
        prompt,
        id=workflow_id,
        task_queue="catcher-agent-queue",
        memo={"mcp_servers": enabled_server_names},
    )


if __name__ == "__main__":
    asyncio.run(main())
