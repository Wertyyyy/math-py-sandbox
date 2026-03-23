from __future__ import annotations

import asyncio
import re

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session() as session:
        reset_result = await session.call_tool("python_reset", {"session_id": "missing-session"})
        reset_payload = tool_json(reset_result)
        assert reset_payload == {"status": "not_found"}

        default_result = await session.call_tool(
            "python_exec",
            {"code": "print('default session created')"},
        )
        default_payload = tool_json(default_result)
        default_session_id = default_payload["session_id"]
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            default_session_id,
        )
        assert default_payload["output"] == "default session created\n"

        reused_default = await session.call_tool(
            "python_exec",
            {
                "code": "state_value = 123\nprint(f'state={state_value}')",
                "session_id": default_session_id,
            },
        )
        reused_payload = tool_json(reused_default)
        assert reused_payload["output"] == "state=123\n"

        special_code = (
            """message = 'quote:\\' double:\\" backslash:\\\\ unicode:你好'\n"""
            "payload = {'a': 1, 'b': [2, 3], 'nested': {'k': 'v'}}\n"
            "print(message)\n"
            "print(payload)\n"
            "print('line1\\nline2')\n"
        )
        special_result = await session.call_tool(
            "python_exec",
            {"code": special_code, "session_id": "special-payloads"},
        )
        special_payload = tool_json(special_result)
        assert "quote:' double:\" backslash:\\ unicode:你好" in special_payload["output"]
        assert "{'a': 1, 'b': [2, 3], 'nested': {'k': 'v'}}" in special_payload["output"]
        assert "line1\nline2" in special_payload["output"]

        syntax_error_result = await session.call_tool(
            "python_exec",
            {
                "code": "def broken(:\n    pass",
                "session_id": "syntax-error-session",
            },
        )
        syntax_error_payload = tool_json(syntax_error_result)
        syntax_error_text = syntax_error_payload.get("error", "") + syntax_error_payload.get("output", "")
        assert "SyntaxError" in syntax_error_text

        recovery_result = await session.call_tool(
            "python_exec",
            {
                "code": "print('recovered after syntax error')",
                "session_id": "syntax-error-session",
            },
        )
        recovery_payload = tool_json(recovery_result)
        assert recovery_payload["output"] == "recovered after syntax error\n"

        async def use_session(session_id: str, value: int) -> str:
            result = await session.call_tool(
                "python_exec",
                {
                    "code": f"marker = {value}\nprint(marker)",
                    "session_id": session_id,
                },
            )
            payload = tool_json(result)
            return payload["output"]

        outputs = await asyncio.gather(
            use_session("concurrent-a", 111),
            use_session("concurrent-b", 222),
        )
        assert outputs == ["111\n", "222\n"]

        cross_check_a = await session.call_tool(
            "python_exec",
            {"code": "print(marker)", "session_id": "concurrent-a"},
        )
        cross_check_a_payload = tool_json(cross_check_a)
        assert cross_check_a_payload["output"] == "111\n"

        cross_check_b = await session.call_tool(
            "python_exec",
            {"code": "print(marker)", "session_id": "concurrent-b"},
        )
        cross_check_b_payload = tool_json(cross_check_b)
        assert cross_check_b_payload["output"] == "222\n"


def test_mcp_stdio_edge_cases() -> None:
    asyncio.run(scenario())
