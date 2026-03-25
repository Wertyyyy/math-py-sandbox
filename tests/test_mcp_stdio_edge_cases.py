from __future__ import annotations

import asyncio
import re

from tests.helpers import open_client_session, tool_json


async def scenario() -> None:
    async with open_client_session() as session:
        reset_result = await session.call_tool(
            "python_reset_session",
            {},
            meta={"client_id": "missing-session"},
        )
        reset_payload = tool_json(reset_result)
        assert reset_payload == {"session_status": "not_found"}

        default_result = await session.call_tool(
            "python_exec",
            {"code": "print('default session created')"},
            meta={"client_id": "default-session"},
        )
        default_payload = tool_json(default_result)
        default_session_id = "default-session"
        assert default_payload["interpreter_output"] == "default session created\n"

        reused_default = await session.call_tool(
            "python_exec",
            {
                "code": "state_value = 123\nprint(f'state={state_value}')",
            },
            meta={"client_id": default_session_id},
        )
        reused_payload = tool_json(reused_default)
        assert reused_payload["interpreter_output"] == "state=123\n"

        special_code = (
            """message = 'quote:\\' double:\\" backslash:\\\\ unicode:你好'\n"""
            "payload = {'a': 1, 'b': [2, 3], 'nested': {'k': 'v'}}\n"
            "print(message)\n"
            "print(payload)\n"
            "print('line1\\nline2')\n"
        )
        special_result = await session.call_tool(
            "python_exec",
            {"code": special_code},
            meta={"client_id": "special-payloads"},
        )
        special_payload = tool_json(special_result)
        assert "quote:' double:\" backslash:\\ unicode:你好" in special_payload["interpreter_output"]
        assert "{'a': 1, 'b': [2, 3], 'nested': {'k': 'v'}}" in special_payload["interpreter_output"]
        assert "line1\nline2" in special_payload["interpreter_output"]

        syntax_error_result = await session.call_tool(
            "python_exec",
            {
                "code": "def broken(:\n    pass",
            },
            meta={"client_id": "syntax-error-session"},
        )
        syntax_error_payload = tool_json(syntax_error_result)
        assert syntax_error_payload["execution_status"] == "code_error"
        assert syntax_error_payload["error_type"] == "code_execution_error"
        assert "SyntaxError" in syntax_error_payload["interpreter_output"]

        recovery_result = await session.call_tool(
            "python_exec",
            {
                "code": "print('recovered after syntax error')",
            },
            meta={"client_id": "syntax-error-session"},
        )
        recovery_payload = tool_json(recovery_result)
        assert recovery_payload["interpreter_output"] == "recovered after syntax error\n"

        async def use_session(session_id: str, value: int) -> str:
            result = await session.call_tool(
                "python_exec",
                {
                    "code": f"marker = {value}\nprint(marker)",
                },
                meta={"client_id": session_id},
            )
            payload = tool_json(result)
            return payload["interpreter_output"]

        outputs = await asyncio.gather(
            use_session("concurrent-a", 111),
            use_session("concurrent-b", 222),
        )
        assert outputs == ["111\n", "222\n"]

        cross_check_a = await session.call_tool(
            "python_exec",
            {"code": "print(marker)"},
            meta={"client_id": "concurrent-a"},
        )
        cross_check_a_payload = tool_json(cross_check_a)
        assert cross_check_a_payload["interpreter_output"] == "111\n"

        cross_check_b = await session.call_tool(
            "python_exec",
            {"code": "print(marker)"},
            meta={"client_id": "concurrent-b"},
        )
        cross_check_b_payload = tool_json(cross_check_b)
        assert cross_check_b_payload["interpreter_output"] == "222\n"


def test_mcp_stdio_edge_cases() -> None:
    asyncio.run(scenario())
