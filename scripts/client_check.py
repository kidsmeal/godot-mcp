"""End-to-end check: launch the server over stdio exactly as a client would,
initialize, list tools, and call a couple. Proves Claude Code registration will work."""
import asyncio
import pathlib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = pathlib.Path(__file__).resolve().parents[1]
PY = REPO / ".venv" / "Scripts" / "python.exe"
MAIN = REPO / "main.py"


async def main():
    params = StdioServerParameters(command=str(PY), args=[str(MAIN)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS:", ", ".join(t.name for t in tools.tools))
            for name, args in [
                ("godot_version", {}),
                ("godot_member", {"class_name": "Tween", "member": "tween_property"}),
                ("project_catalog", {"kind": "damage_types"}),
            ]:
                res = await session.call_tool(name, args)
                print(f"\n--- {name}{args} ---")
                print(res.content[0].text)


asyncio.run(main())
