import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")


async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER, "--transport", "stdio"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])
            try:
                res = await session.call_tool("check_auth", {})
                text = "".join(
                    getattr(c, "text", "") for c in res.content
                )
                print("CHECK_AUTH_OK:", text[:800])
            except Exception as e:  # noqa: BLE001
                print("CHECK_AUTH_ERROR:", repr(e)[:800])


if __name__ == "__main__":
    asyncio.run(main())
