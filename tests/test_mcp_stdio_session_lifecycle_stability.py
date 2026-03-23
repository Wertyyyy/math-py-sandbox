from __future__ import annotations

import asyncio
import statistics
import time

from tests.helpers import open_client_session, tool_json


async def create_use_and_reset(session, session_id: str, cycle_index: int) -> dict[str, float]:
    timings: dict[str, float] = {}

    started_at = time.perf_counter()
    first_result = await session.call_tool(
        "python_exec",
        {
            "code": (
                "counter = 1\n"
                "print(counter)\n"
                "print(counter + 1)\n"
            ),
            "session_id": session_id,
        },
    )
    timings["create_and_first_exec"] = time.perf_counter() - started_at
    first_payload = tool_json(first_result)
    assert first_payload["output"].splitlines() == ["1", "2"]

    started_at = time.perf_counter()
    second_result = await session.call_tool(
        "python_exec",
        {
            "code": (
                f"import math\n"
                f"value = {cycle_index + 2}\n"
                "print(math.sqrt(value * value))\n"
                "print(value * 3)\n"
            ),
            "session_id": session_id,
        },
    )
    timings["second_exec"] = time.perf_counter() - started_at
    second_payload = tool_json(second_result)
    assert abs(float(second_payload["output"].splitlines()[0]) - float(cycle_index + 2)) < 1e-9

    started_at = time.perf_counter()
    reset_result = await session.call_tool("python_reset", {"session_id": session_id})
    timings["reset"] = time.perf_counter() - started_at
    reset_payload = tool_json(reset_result)
    assert reset_payload == {"status": "reset"}

    started_at = time.perf_counter()
    recreated_result = await session.call_tool(
        "python_exec",
        {
            "code": "print('session recreated')",
            "session_id": session_id,
        },
    )
    timings["recreate_after_reset"] = time.perf_counter() - started_at
    recreated_payload = tool_json(recreated_result)
    assert recreated_payload["output"] == "session recreated\n"

    started_at = time.perf_counter()
    cleanup_result = await session.call_tool("python_reset", {"session_id": session_id})
    timings["cleanup_reset"] = time.perf_counter() - started_at
    cleanup_payload = tool_json(cleanup_result)
    assert cleanup_payload == {"status": "reset"}

    return timings


async def scenario() -> None:
    cycles = 25
    create_and_exec_samples: list[float] = []
    second_exec_samples: list[float] = []
    reset_samples: list[float] = []
    recreate_samples: list[float] = []

    async with open_client_session(exec_timeout_seconds=10) as session:
        await session.list_tools()

        for index in range(cycles):
            session_id = f"stability-session-{index + 1}"
            timings = await create_use_and_reset(session, session_id, index)
            create_and_exec_samples.append(timings["create_and_first_exec"])
            second_exec_samples.append(timings["second_exec"])
            reset_samples.append(timings["reset"])
            recreate_samples.append(timings["recreate_after_reset"])
            print(
                "stability_cycle_{}: create_first_exec={:.3f}s second_exec={:.3f}s reset={:.3f}s recreate={:.3f}s".format(
                    index + 1,
                    timings["create_and_first_exec"],
                    timings["second_exec"],
                    timings["reset"],
                    timings["recreate_after_reset"],
                )
            )

    def summary(values: list[float]) -> tuple[float, float, float]:
        return min(values), statistics.median(values), max(values)

    create_min, create_median, create_max = summary(create_and_exec_samples)
    second_min, second_median, second_max = summary(second_exec_samples)
    reset_min, reset_median, reset_max = summary(reset_samples)
    recreate_min, recreate_median, recreate_max = summary(recreate_samples)

    print(
        "stability_summary: create_first_exec min={:.3f}s median={:.3f}s max={:.3f}s | second_exec min={:.3f}s median={:.3f}s max={:.3f}s | reset min={:.3f}s median={:.3f}s max={:.3f}s | recreate min={:.3f}s median={:.3f}s max={:.3f}s".format(
            create_min,
            create_median,
            create_max,
            second_min,
            second_median,
            second_max,
            reset_min,
            reset_median,
            reset_max,
            recreate_min,
            recreate_median,
            recreate_max,
        )
    )

    assert len(create_and_exec_samples) == cycles
    assert len(second_exec_samples) == cycles
    assert len(reset_samples) == cycles
    assert len(recreate_samples) == cycles
    assert all(duration > 0 for duration in create_and_exec_samples)
    assert all(duration > 0 for duration in second_exec_samples)
    assert all(duration > 0 for duration in reset_samples)
    assert all(duration > 0 for duration in recreate_samples)

    # Keep the test resilient to shared CI variance while still flagging clear regressions.
    assert create_max < create_median * 5
    assert recreate_max < recreate_median * 5


def test_mcp_stdio_session_lifecycle_stability() -> None:
    asyncio.run(scenario())
