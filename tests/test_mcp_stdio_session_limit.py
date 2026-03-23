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
                    "session_id": session_id,
                },
            )
            payload = tool_json(result)
            assert payload["session_id"] == session_id
            assert payload["output"] == f"session {index} ready\n"

        rejected_result = await session.call_tool(
            "python_exec",
            {"code": "print('should not start')", "session_id": "limit-session-4"},
        )
        rejected_payload = tool_json(rejected_result)
        error_text = rejected_payload.get("error", "") + rejected_payload.get("output", "")
        assert "maximum active session limit" in error_text.lower()
        assert rejected_payload["session_id"] == "limit-session-4"

        existing_result = await session.call_tool(
            "python_exec",
            {
                "code": "print('existing session still works at limit')",
                "session_id": "limit-session-2",
            },
        )
        existing_payload = tool_json(existing_result)
        assert existing_payload["session_id"] == "limit-session-2"
        assert existing_payload["output"] == "existing session still works at limit\n"

        reset_result = await session.call_tool("python_reset", {"session_id": "limit-session-1"})
        reset_payload = tool_json(reset_result)
        assert reset_payload == {"status": "reset"}

        recovered_result = await session.call_tool(
            "python_exec",
            {"code": "print('session 4 recovered')", "session_id": "limit-session-4"},
        )
        recovered_payload = tool_json(recovered_result)
        assert recovered_payload["session_id"] == "limit-session-4"
        assert recovered_payload["output"] == "session 4 recovered\n"


def test_mcp_stdio_session_limit() -> None:
    asyncio.run(scenario())
