from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session(
        exec_timeout_seconds=10,
        process_time_limit_seconds=3,
    ) as session:
        result = await session.call_tool(
            "python_exec",
            {
                "code": "import time\nprint('starting work')\ntime.sleep(5)\nprint('finished work')",
            },
            meta={"client_id": "nsjail-timeout"},
        )
        payload = tool_json(result)
        assert payload["execution_status"] == "session_error"
        assert payload["session_status"] == "terminated"
        assert payload["error_type"] == "code_triggered_session_error"
        assert any(
            term in payload["error_message"].lower()
            for term in ("terminated", "timed out")
        )

        result = await session.call_tool(
            "python_exec",
            {
                "code": "print('reuse after nsjail kill')",
            },
            meta={"client_id": "nsjail-timeout"},
        )
        payload = tool_json(result)
        if payload["execution_status"] != "success":
            result = await session.call_tool(
                "python_exec",
                {
                    "code": "print('reuse after nsjail kill')",
                },
                meta={"client_id": "nsjail-timeout"},
            )
            payload = tool_json(result)
        assert payload["execution_status"] == "success"
        assert payload["interpreter_output"] == "reuse after nsjail kill\n"


def test_mcp_stdio_nsjail_timeout() -> None:
    asyncio.run(scenario())
