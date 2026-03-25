from __future__ import annotations

import asyncio

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session(max_sessions=3) as session:
        session_ids = ["limit-session-1", "limit-session-2", "limit-session-3"]

        for index, session_id in enumerate(session_ids, start=1):
            result = await session.call_tool(
                "python_exec",
                {
                    "code": f"print('session {index} ready')",
                },
                meta={"client_id": session_id},
            )
            payload = tool_json(result)
            assert payload["interpreter_output"] == f"session {index} ready\n"

        rejected_result = await session.call_tool(
            "python_exec",
            {"code": "print('should not start')"},
            meta={"client_id": "limit-session-4"},
        )
        rejected_payload = tool_json(rejected_result)
        assert rejected_payload["execution_status"] == "session_error"
        assert rejected_payload["session_status"] == "unavailable"
        assert rejected_payload["error_type"] == "session_infrastructure_error"
        assert "maximum active session limit" in rejected_payload["error_message"].lower()

        existing_result = await session.call_tool(
            "python_exec",
            {
                "code": "print('existing session still works at limit')",
            },
            meta={"client_id": "limit-session-2"},
        )
        existing_payload = tool_json(existing_result)
        assert existing_payload["interpreter_output"] == "existing session still works at limit\n"

        reset_result = await session.call_tool(
            "python_reset_session",
            {},
            meta={"client_id": "limit-session-1"},
        )
        reset_payload = tool_json(reset_result)
        assert reset_payload == {"session_status": "reset"}

        recovered_result = await session.call_tool(
            "python_exec",
            {"code": "print('session 4 recovered')"},
            meta={"client_id": "limit-session-4"},
        )
        recovered_payload = tool_json(recovered_result)
        assert recovered_payload["interpreter_output"] == "session 4 recovered\n"


def test_mcp_stdio_session_limit() -> None:
    asyncio.run(scenario())
