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

    await client.execute_workflow(
        workflow_name,
        "Please tell me a joke",
        id=workflow_id,
        task_queue="catcher-agent-queue",
    )


if __name__ == "__main__":
    asyncio.run(main())
