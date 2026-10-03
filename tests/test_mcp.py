import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_stdio_registers_only_read_tools():
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
            }
            assert all(t.annotations.readOnlyHint for t in response.tools)

    asyncio.run(exercise())
