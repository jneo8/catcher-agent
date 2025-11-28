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

    enabled_server_names = ["kubernetes"]

    await client.execute_workflow(
        workflow_name,
        "Please trouble shooting for me the failure pod in all the namespace. Please include the failure pod information & why it's failed",
        id=workflow_id,
        task_queue="catcher-agent-queue",
        memo={"mcp_servers": enabled_server_names},
    )


if __name__ == "__main__":
    asyncio.run(main())
