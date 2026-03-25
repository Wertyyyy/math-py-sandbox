from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session() as session:
        tools_response = await session.list_tools()
        tool_names = {tool.name for tool in tools_response}
        assert {"python_create_session", "python_exec", "python_reset_session"} <= tool_names

        client_id = "happy-path"

        result = await session.call_tool(
            "python_exec",
            {"code": "print('hello from pytest')"},
            meta={"client_id": client_id},
        )
        payload = tool_json(result)
        assert payload["interpreter_output"] == "hello from pytest\n"

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import math\nprint(math.sqrt(16))",
            },
            meta={"client_id": client_id},
        )
        payload = tool_json(result)
        assert payload["interpreter_output"] == "4.0\n"

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import numpy as np\nprint(np.array([1, 2, 3]).sum())",
            },
            meta={"client_id": client_id},
        )
        payload = tool_json(result)
        assert payload["interpreter_output"] == "6\n"

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import sympy as sp\nx = sp.Symbol('x')\nprint(sp.solve(x**2 - 4, x))",
            },
            meta={"client_id": client_id},
        )
        payload = tool_json(result)
        assert payload["interpreter_output"].strip() == "[-2, 2]"


def test_mcp_stdio_happy_path() -> None:
    asyncio.run(scenario())
