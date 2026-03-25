from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session() as session:
        tools_response = await session.list_tools()
        tool_names = {tool.name for tool in tools_response}
        assert "python_create_session" in tool_names

        client_id = "session-creation"

        created_result = await session.call_tool(
            "python_create_session",
            {},
            meta={"client_id": client_id},
        )
        created_payload = tool_json(created_result)
        assert created_payload == {"session_status": "created"}

        exec_result = await session.call_tool(
            "python_exec",
            {
                "code": "session_value = 42\nprint(session_value)",
            },
            meta={"client_id": client_id},
        )
        exec_payload = tool_json(exec_result)
        assert exec_payload["interpreter_output"] == "42\n"

        explicit_result = await session.call_tool(
            "python_create_session",
            {},
            meta={"client_id": client_id},
        )
        explicit_payload = tool_json(explicit_result)
        assert explicit_payload == {"session_status": "existing"}

        duplicate_result = await session.call_tool(
            "python_create_session",
            {},
            meta={"client_id": client_id},
        )
        duplicate_payload = tool_json(duplicate_result)
        assert duplicate_payload == {"session_status": "existing"}

        reset_result = await session.call_tool(
            "python_reset_session",
            {},
            meta={"client_id": client_id},
        )
        reset_payload = tool_json(reset_result)
        assert reset_payload == {"session_status": "reset"}

        recreated_result = await session.call_tool(
            "python_create_session",
            {},
            meta={"client_id": client_id},
        )
        recreated_payload = tool_json(recreated_result)
        assert recreated_payload == {"session_status": "created"}


def test_mcp_stdio_session_creation() -> None:
    asyncio.run(scenario())