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
            },
            meta={"client_id": timeout_session_id},
        )
        payload = tool_json(result)
        assert payload["execution_status"] == "session_error"
        assert payload["session_status"] == "terminated"
        assert payload["error_type"] == "code_triggered_session_error"
        assert "timed out" in payload["error_message"].lower()

        result = await session.call_tool(
            "python_exec",
            {
                "code": "print('reuse after timeout')",
            },
            meta={"client_id": timeout_session_id},
        )
        payload = tool_json(result)
        if payload["execution_status"] != "success":
            result = await session.call_tool(
                "python_exec",
                {
                    "code": "print('reuse after timeout')",
                },
                meta={"client_id": timeout_session_id},
            )
            payload = tool_json(result)
        assert payload["execution_status"] == "success"
        assert payload["interpreter_output"] == "reuse after timeout\n"

        result = await session.call_tool(
            "python_exec",
            {"code": "print('fresh session still works')"},
            meta={"client_id": "timeout-workflow-fresh"},
        )
        payload = tool_json(result)
        assert payload["interpreter_output"] == "fresh session still works\n"


def test_mcp_stdio_timeout() -> None:
    asyncio.run(scenario())
