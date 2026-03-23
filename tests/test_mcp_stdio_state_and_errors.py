from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session() as session:
        session_id = "stateful-workflow"

        result = await session.call_tool(
            "python_exec",
            {
                "code": "counter = 41\ndef bump(value):\n    return value + 1\nprint(counter)\nprint(bump(counter))",
                "session_id": session_id,
            },
        )
        payload = tool_json(result)
        assert payload["output"] == "41\n42\n"

        result = await session.call_tool(
            "python_exec",
            {"code": "print(counter * 2)", "session_id": session_id},
        )
        payload = tool_json(result)
        assert payload["output"] == "82\n"

        result = await session.call_tool(
            "python_exec",
            {"code": "print(counter)", "session_id": "isolated-session"},
        )
        payload = tool_json(result)
        error_text = payload.get("error", "") + payload.get("output", "")
        assert "NameError" in error_text

        result = await session.call_tool(
            "python_exec",
            {"code": "1 / 0", "session_id": session_id},
        )
        payload = tool_json(result)
        assert payload["session_id"] == session_id
        assert "ZeroDivisionError" in payload["output"]

        result = await session.call_tool(
            "python_exec",
            {"code": "print('still alive after exception')", "session_id": session_id},
        )
        payload = tool_json(result)
        assert payload["output"] == "still alive after exception\n"

        reset_result = await session.call_tool("python_reset", {"session_id": session_id})
        reset_payload = tool_json(reset_result)
        assert reset_payload == {"status": "reset"}

        result = await session.call_tool(
            "python_exec",
            {"code": "print(counter)", "session_id": session_id},
        )
        payload = tool_json(result)
        error_text = payload.get("error", "") + payload.get("output", "")
        assert "terminated" in error_text.lower() or "nameerror" in error_text.lower()


def test_mcp_stdio_state_and_errors() -> None:
    asyncio.run(scenario())
