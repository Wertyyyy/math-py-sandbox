from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session() as session:
        tools_response = await session.list_tools()
        tool_names = {tool.name for tool in tools_response.tools}
        assert {"python_exec", "python_reset"} <= tool_names

        result = await session.call_tool(
            "python_exec",
            {"code": "print('hello from pytest')", "session_id": "happy-path"},
        )
        payload = tool_json(result)
        assert payload["session_id"] == "happy-path"
        assert payload["output"] == "hello from pytest\n"

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import math\nprint(math.sqrt(16))",
                "session_id": "happy-path",
            },
        )
        payload = tool_json(result)
        assert payload["output"] == "4.0\n"

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import numpy as np\nprint(np.array([1, 2, 3]).sum())",
                "session_id": "happy-path",
            },
        )
        payload = tool_json(result)
        assert payload["output"] == "6\n"

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import sympy as sp\nx = sp.Symbol('x')\nprint(sp.solve(x**2 - 4, x))",
                "session_id": "happy-path",
            },
        )
        payload = tool_json(result)
        assert payload["output"].strip() == "[-2, 2]"


def test_mcp_stdio_happy_path() -> None:
    asyncio.run(scenario())
