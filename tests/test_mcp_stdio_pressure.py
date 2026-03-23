from __future__ import annotations

import asyncio
import time

from tests.helpers import open_client_session, tool_json


async def worker(session, session_id: str, repeat_count: int) -> None:
    for iteration in range(repeat_count):
        numpy_result = await session.call_tool(
            "python_exec",
            {
                "code": (
                    "import numpy as np\n"
                    f"values = np.arange(1, {100 + iteration})\n"
                    "print(int(values.sum()))\n"
                    "print(int(values.mean()))\n"
                ),
                "session_id": session_id,
            },
        )
        numpy_payload = tool_json(numpy_result)
        assert len(numpy_payload["output"].splitlines()) == 2

        scipy_result = await session.call_tool(
            "python_exec",
            {
                "code": (
                    "import scipy.integrate as integrate\n"
                    "import scipy.optimize as opt\n"
                    "root = opt.brentq(lambda x: x**2 - 4, 0, 3)\n"
                    "area, _ = integrate.quad(lambda x: x, 0, 4)\n"
                    "print(round(root, 6))\n"
                    "print(round(area, 6))\n"
                ),
                "session_id": session_id,
            },
        )
        scipy_payload = tool_json(scipy_result)
        assert scipy_payload["output"].splitlines() == ["2.0", "8.0"]

        sympy_result = await session.call_tool(
            "python_exec",
            {
                "code": (
                    "import sympy as sp\n"
                    "x = sp.Symbol('x')\n"
                    "print(sp.solve(sp.Eq(x**2 - 1, 0), x))\n"
                    "print(sp.simplify((x**2 - 1) / (x - 1)))\n"
                ),
                "session_id": session_id,
            },
        )
        sympy_payload = tool_json(sympy_result)
        assert "[-1, 1]" in sympy_payload["output"]
        assert "x + 1" in sympy_payload["output"]


async def scenario() -> None:
    started_at = time.perf_counter()

    async with open_client_session(exec_timeout_seconds=10, process_time_limit_seconds=120) as session:
        await session.list_tools()

        workers = [
            worker(session, f"pressure-session-{index + 1}", 4)
            for index in range(4)
        ]
        await asyncio.gather(*workers)

        for index in range(4):
            reset_result = await session.call_tool(
                "python_reset",
                {"session_id": f"pressure-session-{index + 1}"},
            )
            reset_payload = tool_json(reset_result)
            assert reset_payload == {"status": "reset"}

    elapsed = time.perf_counter() - started_at
    print(f"pressure_test_elapsed: {elapsed:.3f}s")
    assert elapsed > 0


def test_mcp_stdio_pressure() -> None:
    asyncio.run(scenario())
