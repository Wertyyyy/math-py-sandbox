from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session(
        exec_timeout_seconds=10,
        process_time_limit_seconds=2,
    ) as session:
        result = await session.call_tool(
            "python_exec",
            {
                "code": "import time\nprint('starting work')\ntime.sleep(5)\nprint('finished work')",
                "session_id": "nsjail-timeout",
            },
        )
        payload = tool_json(result)
        assert payload["session_id"] == "nsjail-timeout"
        error_text = payload.get("error", "") + payload.get("output", "")
        assert "terminated" in error_text.lower() or "timed out" in error_text.lower()

        result = await session.call_tool(
            "python_exec",
            {
                "code": "print('reuse after nsjail kill')",
                "session_id": "nsjail-timeout",
            },
        )
        payload = tool_json(result)
        error_text = payload.get("error", "") + payload.get("output", "")
        assert "terminated" in error_text.lower() or "not found" in error_text.lower()


def test_mcp_stdio_nsjail_timeout() -> None:
    asyncio.run(scenario())
