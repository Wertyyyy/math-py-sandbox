from __future__ import annotations

import asyncio
import time

from tests.helpers import open_client_session, tool_json


async def measure_session_creation_once(session, session_id: str) -> float:
    started_at = time.perf_counter()
    result = await session.call_tool(
        "python_exec",
        {"code": "pass", "session_id": session_id},
    )
    payload = tool_json(result)
    assert payload["session_id"] == session_id
    return time.perf_counter() - started_at


async def scenario() -> None:
    samples: list[float] = []

    async with open_client_session() as session:
        await session.list_tools()

        for index in range(10):
            session_id = f"profile-session-{index + 1}"
            duration = await measure_session_creation_once(session, session_id)
            samples.append(duration)
            print(f"session_creation_run_{index + 1}: {duration:.3f}s")

    average = sum(samples) / len(samples)
    print(f"session_creation_average: {average:.3f}s")

    assert len(samples) == 10
    assert all(duration > 0 for duration in samples)


def test_mcp_stdio_profile_session_creation() -> None:
    asyncio.run(scenario())
