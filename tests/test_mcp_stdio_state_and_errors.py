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
            },
            meta={"client_id": session_id},
        )
        payload = tool_json(result)
        assert payload["execution_status"] == "success"
        assert payload["error_type"] is None
        assert payload["interpreter_output"] == "41\n42\n"

        result = await session.call_tool(
            "python_exec",
            {"code": "print(counter * 2)"},
            meta={"client_id": session_id},
        )
        payload = tool_json(result)
        assert payload["execution_status"] == "success"
        assert payload["error_type"] is None
        assert payload["interpreter_output"] == "82\n"

        result = await session.call_tool(
            "python_exec",
            {"code": "print(counter)"},
            meta={"client_id": "isolated-session"},
        )
        payload = tool_json(result)
        assert payload["execution_status"] == "code_error"
        assert payload["error_type"] == "code_execution_error"
        assert "NameError" in payload["interpreter_output"]

        result = await session.call_tool(
            "python_exec",
            {"code": "1 / 0"},
            meta={"client_id": session_id},
        )
        payload = tool_json(result)
        assert payload["execution_status"] == "code_error"
        assert payload["error_type"] == "code_execution_error"
        assert "ZeroDivisionError" in payload["interpreter_output"]

        result = await session.call_tool(
            "python_exec",
            {"code": "print('still alive after exception')"},
            meta={"client_id": session_id},
        )
        payload = tool_json(result)
        assert payload["interpreter_output"] == "still alive after exception\n"

        reset_result = await session.call_tool(
            "python_reset_session",
            {},
            meta={"client_id": session_id},
        )
        reset_payload = tool_json(reset_result)
        assert reset_payload == {"session_status": "reset"}

        result = await session.call_tool(
            "python_exec",
            {"code": "print(counter)"},
            meta={"client_id": session_id},
        )
        payload = tool_json(result)
        assert payload["execution_status"] == "code_error"
        assert payload["error_type"] == "code_execution_error"
        assert "NameError" in payload["interpreter_output"]


def test_mcp_stdio_state_and_errors() -> None:
    asyncio.run(scenario())
