import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_stdio_registers_read_and_send_tools():
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "server.mcp_adapter"], env=dict(os.environ)
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            response = await client.list_tools()
            assert {t.name for t in response.tools} == {
                "get_recent_messages",
                "search_messages",
                "list_conversations",
                "get_collector_status",
                "get_conversation_context",
                "send_message",
                "get_message_send_status",
            }
            send = next(t for t in response.tools if t.name == "send_message")
            assert not send.annotations.readOnlyHint
            assert send.annotations.openWorldHint and send.annotations.destructiveHint
            assert all(
                t.annotations.readOnlyHint for t in response.tools if t.name != "send_message"
            )

    asyncio.run(exercise())
