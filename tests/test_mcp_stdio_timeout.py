from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session(exec_timeout_seconds=2) as session:
        timeout_session_id = "timeout-workflow"

        result = await session.call_tool(
            "python_exec",
            {
                "code": "import time\nprint('starting long task')\ntime.sleep(5)\nprint('finished')",
                "session_id": timeout_session_id,
            },
        )
        payload = tool_json(result)
        assert payload["session_id"] == timeout_session_id
        assert "timed out" in payload["error"].lower()

        result = await session.call_tool(
            "python_exec",
            {
                "code": "print('reuse after timeout')",
                "session_id": timeout_session_id,
            },
        )
        payload = tool_json(result)
        error_text = payload.get("error", "") + payload.get("output", "")
        assert "terminated" in error_text.lower() or "broken pipe" in error_text.lower()

        result = await session.call_tool(
            "python_exec",
            {"code": "print('fresh session still works')"},
        )
        payload = tool_json(result)
        assert payload["output"] == "fresh session still works\n"


def test_mcp_stdio_timeout() -> None:
    asyncio.run(scenario())
